"""Regenerate BioAI PDFs for eligible female booked participants.

For participants in running engagements (or any status when ``engagement_id`` is
set) with a Healthians booking_id and an existing bio-ai-reports permanent URL
on the primary assessment instance:
1. Verify MetSights blood parameters are complete.
2. Draft blood questionnaire answers from IHR (updated unit codes) and re-push
   all Metsights categories linked to the primary assessment package.
3. Refresh individual_health_report.reports from MetSights.
4. Regenerate the PDF at the same slug via POST /api/reports/regenerate.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.seed.blood_parameters_registry import (
    ADVANCED_BLOOD_PARAMETER_CATEGORY_KEY,
    BLOOD_PARAMETER_CATEGORY_KEY,
)
from modules.assessments.models import AssessmentInstance, AssessmentPackage
from modules.assessments.repository import AssessmentsRepository
from modules.audit.cron_sync_logging import tracked_integration_call
from modules.bioai_report.pdf_registration import (
    extract_slug_from_report_url,
    is_bio_ai_assessment_type,
    regenerate_permanent_bio_ai_report_url,
)
from modules.engagements.models import Engagement, EngagementParticipant
from modules.metsights.service import MetsightsService
from modules.notifications.load_bioai_reports import (
    _fetch_metsights_report_json,
    _metsights_blood_parameters_url,
)
from modules.questionnaire.repository import QuestionnaireRepository
from modules.reports.models import IndividualHealthReport
from modules.users.models import User

if TYPE_CHECKING:
    from modules.assessments.service import AssessmentsService
    from modules.metsights.sync_service import MetsightsSyncService

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, int, int, int], None]

_FEMALE_GENDERS = ("female", "f", "2")
_METSIGHTS_CATEGORY_PUSH_ORDER = (
    "physical-measurement",
    "vitals",
    "diet-lifestyle-parameters",
    BLOOD_PARAMETER_CATEGORY_KEY,
    ADVANCED_BLOOD_PARAMETER_CATEGORY_KEY,
)


async def _get_regenerate_candidates(
    db: AsyncSession,
    today: date,
    *,
    engagement_id: int | None = None,
) -> list[tuple]:
    """Female booked participants on primary assessment with an existing report_url."""
    query = (
        select(
            EngagementParticipant.user_id,
            Engagement.engagement_id,
            AssessmentInstance.assessment_instance_id,
            AssessmentInstance.package_id,
            AssessmentInstance.metsights_record_id,
            AssessmentPackage.assessment_type_code,
            IndividualHealthReport.report_id,
            IndividualHealthReport.reports,
            IndividualHealthReport.report_url,
        )
        .join(Engagement, Engagement.engagement_id == EngagementParticipant.engagement_id)
        .join(User, User.user_id == EngagementParticipant.user_id)
        .join(
            AssessmentInstance,
            (AssessmentInstance.engagement_id == EngagementParticipant.engagement_id)
            & (AssessmentInstance.user_id == EngagementParticipant.user_id)
            & (AssessmentInstance.package_id == Engagement.assessment_package_id),
        )
        .join(AssessmentPackage, AssessmentPackage.package_id == AssessmentInstance.package_id)
        .join(
            IndividualHealthReport,
            IndividualHealthReport.assessment_instance_id
            == AssessmentInstance.assessment_instance_id,
        )
        .where(EngagementParticipant.engagement_date <= today)
        .where(Engagement.assessment_package_id.isnot(None))
        .where(EngagementParticipant.booking_id.isnot(None))
        .where(EngagementParticipant.booking_id != "")
        .where(func.lower(func.trim(User.gender)).in_(_FEMALE_GENDERS))
        .where(AssessmentInstance.metsights_record_id.isnot(None))
        .where(AssessmentInstance.metsights_record_id != "")
        .where(IndividualHealthReport.report_url.isnot(None))
        .where(IndividualHealthReport.report_url != "")
    )
    if engagement_id is not None:
        query = query.where(Engagement.engagement_id == engagement_id)
    else:
        query = query.where(Engagement.status.ilike("running"))
    query = query.order_by(
        Engagement.engagement_id.asc(),
        EngagementParticipant.user_id.asc(),
    )
    result = await db.execute(query)
    return result.all()


async def _metsights_category_keys_for_package(
    db: AsyncSession,
    *,
    package_id: int,
) -> list[str]:
    """Return Metsights category keys linked to the primary assessment package."""
    assessments_repo = AssessmentsRepository()
    questionnaire_repo = QuestionnaireRepository()
    links = await assessments_repo.list_package_categories(db, package_id=package_id)
    linked: set[str] = set()
    for link in links:
        category = await questionnaire_repo.get_category_by_id(db, int(link.category_id))
        if category is None:
            continue
        if (category.category_of or "").strip().lower() != "metsights":
            continue
        key = (category.category_key or "").strip()
        if key:
            linked.add(key)
    return [key for key in _METSIGHTS_CATEGORY_PUSH_ORDER if key in linked]


async def _repush_metsights_categories_before_regenerate(
    db: AsyncSession,
    *,
    assessments_service: "AssessmentsService",
    sync_service: "MetsightsSyncService",
    user_id: int,
    engagement_id: int,
    instance_id: int,
    package_id: int,
    details: list[dict[str, Any]],
) -> bool:
    """Draft blood units and re-push all Metsights categories. Returns False on failure."""
    try:
        draft_result = await assessments_service.draft_blood_parameters_from_report(
            db,
            user_id=user_id,
            assessment_instance_id=instance_id,
            allow_completed=True,
        )
        await db.commit()
        details.append({
            "user_id": user_id,
            "engagement_id": engagement_id,
            "action": "drafted",
            "reason": (
                f"drafted {draft_result.get('responses_drafted', 0)} "
                "blood questionnaire responses with updated units"
            ),
        })
    except Exception as exc:
        await db.rollback()
        logger.warning(
            "Blood parameter draft failed for user=%s instance=%s: %s",
            user_id,
            instance_id,
            exc,
        )
        details.append({
            "user_id": user_id,
            "engagement_id": engagement_id,
            "action": "failed",
            "reason": f"blood draft failed: {str(exc)[:120]}",
        })
        return False

    category_keys = await _metsights_category_keys_for_package(
        db,
        package_id=package_id,
    )
    if not category_keys:
        details.append({
            "user_id": user_id,
            "engagement_id": engagement_id,
            "action": "failed",
            "reason": "no metsights categories linked to primary assessment package",
        })
        return False

    for category_key in category_keys:
        try:
            push_result = await sync_service._push_category_to_metsights(
                db,
                assessment_instance_id=instance_id,
                user_id=user_id,
                category_key=category_key,
            )
            await db.commit()
            fields_count = len(push_result.get("fields_pushed") or [])
            details.append({
                "user_id": user_id,
                "engagement_id": engagement_id,
                "action": "pushed",
                "reason": (
                    f"re-pushed {category_key} to Metsights ({fields_count} fields)"
                ),
            })
        except Exception as exc:
            try:
                await db.commit()
            except Exception:
                await db.rollback()
            push_error = getattr(exc, "message", None) or str(exc)
            logger.warning(
                "Metsights category re-push failed for user=%s category=%s: %s",
                user_id,
                category_key,
                exc,
            )
            details.append({
                "user_id": user_id,
                "engagement_id": engagement_id,
                "action": "failed",
                "reason": (
                    f"metsights re-push failed for {category_key}: "
                    f"{str(push_error)[:100]}"
                ),
            })
            return False

    return True


async def regenerate_bioai_reports(
    db: AsyncSession,
    *,
    metsights_service: MetsightsService,
    assessments_service: "AssessmentsService | None" = None,
    sync_service: "MetsightsSyncService | None" = None,
    as_of: date | None = None,
    dry_run: bool = False,
    engagement_id: int | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Refresh MetSights report JSON and regenerate BioAI PDFs at existing slugs."""
    today = as_of or date.today()
    participants = await _get_regenerate_candidates(
        db,
        today,
        engagement_id=engagement_id,
    )
    matched = len(participants)
    regenerated = 0
    skipped = 0
    failed = 0
    details: list[dict[str, Any]] = []

    def _report(done: int) -> None:
        if on_progress is not None:
            on_progress(done, matched, regenerated, skipped, failed)

    _report(0)

    for index, row in enumerate(participants, start=1):
        user_id: int | None = None
        row_engagement_id: int | None = None
        try:
            (
                user_id,
                row_engagement_id,
                instance_id,
                package_id,
                record_id,
                type_code,
                ihr_id,
                _existing_reports,
                existing_report_url,
            ) = row

            record_id = (record_id or "").strip()
            type_code = (type_code or "").strip()
            report_url = (existing_report_url or "").strip()

            if not is_bio_ai_assessment_type(type_code):
                skipped += 1
                details.append({
                    "user_id": user_id,
                    "engagement_id": row_engagement_id,
                    "action": "skipped",
                    "reason": f"primary assessment type {type_code!r} is not BioAI",
                })
                continue

            slug = extract_slug_from_report_url(report_url)
            if not slug:
                skipped += 1
                details.append({
                    "user_id": user_id,
                    "engagement_id": row_engagement_id,
                    "action": "skipped",
                    "reason": "report_url does not contain a bio-ai-reports slug",
                })
                continue

            if dry_run:
                dry_run_reasons = [
                    "would_draft_blood_questionnaires",
                    "would_repush_all_metsights_categories",
                    f"would regenerate slug={slug}",
                ]
                details.append({
                    "user_id": user_id,
                    "engagement_id": row_engagement_id,
                    "action": "dry_run",
                    "reason": ", ".join(dry_run_reasons),
                })
                continue

            if assessments_service is None or sync_service is None:
                skipped += 1
                details.append({
                    "user_id": user_id,
                    "engagement_id": row_engagement_id,
                    "action": "skipped",
                    "reason": "assessments_service and sync_service are required for metsights re-push",
                })
                continue

            bp_data = await tracked_integration_call(
                db,
                provider="metsights",
                api_url=_metsights_blood_parameters_url(record_id=record_id),
                engagement_id=row_engagement_id,
                user_id=user_id,
                request_payload={"record_id": record_id},
                operation=lambda: metsights_service.get_blood_parameters(record_id=record_id),
                reraise=False,
            )
            if bp_data is None:
                skipped += 1
                details.append({
                    "user_id": user_id,
                    "engagement_id": row_engagement_id,
                    "action": "skipped",
                    "reason": "could not check blood parameters on MetSights",
                })
                continue
            if not bp_data.get("is_complete", False):
                skipped += 1
                details.append({
                    "user_id": user_id,
                    "engagement_id": row_engagement_id,
                    "action": "skipped",
                    "reason": "blood parameters not complete on MetSights",
                })
                continue

            if package_id is None:
                skipped += 1
                details.append({
                    "user_id": user_id,
                    "engagement_id": row_engagement_id,
                    "action": "skipped",
                    "reason": "primary assessment package_id missing",
                })
                continue

            repushed = await _repush_metsights_categories_before_regenerate(
                db,
                assessments_service=assessments_service,
                sync_service=sync_service,
                user_id=user_id,
                engagement_id=row_engagement_id,
                instance_id=instance_id,
                package_id=int(package_id),
                details=details,
            )
            if not repushed:
                failed += 1
                continue

            fetched_reports = await _fetch_metsights_report_json(
                db,
                metsights_service=metsights_service,
                record_id=record_id,
                type_code=type_code,
                engagement_id=row_engagement_id,
                user_id=user_id,
            )
            if fetched_reports is None:
                skipped += 1
                details.append({
                    "user_id": user_id,
                    "engagement_id": row_engagement_id,
                    "action": "skipped",
                    "reason": "MetSights get_report returned no data",
                })
                continue

            ihr_result = await db.execute(
                select(IndividualHealthReport).where(
                    IndividualHealthReport.report_id == ihr_id
                )
            )
            ihr = ihr_result.scalar_one_or_none()
            if ihr is None:
                skipped += 1
                details.append({
                    "user_id": user_id,
                    "engagement_id": row_engagement_id,
                    "action": "skipped",
                    "reason": "individual_health_report row missing",
                })
                continue

            ihr.reports = fetched_reports
            await db.flush()

            try:
                await regenerate_permanent_bio_ai_report_url(
                    db,
                    assessment_instance_id=instance_id,
                    report_url=report_url,
                    engagement_id=row_engagement_id,
                    user_id=user_id,
                )
            except Exception as exc:
                await db.rollback()
                failed += 1
                details.append({
                    "user_id": user_id,
                    "engagement_id": row_engagement_id,
                    "action": "failed",
                    "reason": f"bio-ai-reports regenerate failed: {str(exc)[:200]}",
                })
                logger.warning(
                    "BioAI regenerate failed for user=%s engagement=%s instance=%s: %s",
                    user_id,
                    row_engagement_id,
                    instance_id,
                    exc,
                )
                continue

            await db.commit()
            regenerated += 1
            details.append({
                "user_id": user_id,
                "engagement_id": row_engagement_id,
                "action": "regenerated",
                "reason": f"reports refreshed and PDF regenerated at slug={slug}",
            })
        except Exception as exc:
            await db.rollback()
            failed += 1
            details.append({
                "user_id": user_id,
                "engagement_id": row_engagement_id,
                "action": "failed",
                "reason": str(exc)[:200],
            })
            logger.exception("Unexpected BioAI regenerate failure")
        finally:
            _report(index)

    return {
        "dry_run": dry_run,
        "as_of": today.isoformat(),
        "engagement_id": engagement_id,
        "matched": matched,
        "regenerated": regenerated,
        "skipped": skipped,
        "failed": failed,
        "details": details,
    }
