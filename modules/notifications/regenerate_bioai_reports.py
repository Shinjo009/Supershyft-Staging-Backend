"""Regenerate BioAI PDFs for eligible female booked participants.

For participants in running engagements with a Healthians booking_id and an
existing bio-ai-reports permanent URL on the primary assessment instance:
1. Verify MetSights blood parameters are complete.
2. Refresh individual_health_report.reports from MetSights.
3. Regenerate the PDF at the same slug via POST /api/reports/regenerate.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.assessments.models import AssessmentInstance, AssessmentPackage
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
from modules.reports.models import IndividualHealthReport
from modules.users.models import User

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, int, int, int], None]

_FEMALE_GENDERS = ("female", "f", "2")


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
        .where(Engagement.status.ilike("running"))
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
    query = query.order_by(
        Engagement.engagement_id.asc(),
        EngagementParticipant.user_id.asc(),
    )
    result = await db.execute(query)
    return result.all()


async def regenerate_bioai_reports(
    db: AsyncSession,
    *,
    metsights_service: MetsightsService,
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
                record_id,
                type_code,
                ihr_id,
                existing_reports,
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
                details.append({
                    "user_id": user_id,
                    "engagement_id": row_engagement_id,
                    "action": "dry_run",
                    "reason": f"would regenerate slug={slug}",
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
