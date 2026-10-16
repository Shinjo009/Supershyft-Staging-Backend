"""Remediate BioAI generated without archived diagnostic blood PDF.

Ops job: clear blood-parameters answers and IHR BioAI payload, assign a new
MetSights record from the engagement primary package, and re-push non-blood
questionnaire sections to MetSights.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.seed.blood_parameters_registry import BLOOD_PARAMETER_CATEGORY_KEY
from db.transaction import release_request_transaction
from modules.assessments.models import AssessmentInstance, AssessmentPackage
from modules.assessments.repository import AssessmentsRepository
from modules.engagements.models import Engagement, EngagementParticipant
from modules.metsights.service import MetsightsService
from modules.metsights.sync_service import MetsightsSyncService
from modules.notifications.load_bioai_reports import _bioai_report_data_complete
from modules.notifications.push_questionnaires_to_metsights import categories_for_type_code
from modules.questionnaire.repository import QuestionnaireRepository
from modules.reports.blood_booking_reports import (
    get_participant_for_user_engagement,
    has_archived_diagnostic_blood_report,
)
from modules.reports.models import IndividualHealthReport
from modules.reports.repository import ReportsRepository
from modules.users.models import User

logger = logging.getLogger(__name__)

_PRO_BASIC_TYPE_CODES = frozenset({"1", "2"})

ProgressCallback = Callable[[int, int, int, int, int], None]


async def _load_engagement_primary_package_id(
    db: AsyncSession,
    engagement_id: int,
) -> int | None:
    engagement = await db.get(Engagement, engagement_id)
    if engagement is None:
        return None
    package_id = getattr(engagement, "assessment_package_id", None)
    return int(package_id) if package_id is not None else None


async def _select_bad_batch_rows(
    db: AsyncSession,
    *,
    engagement_id: int,
    user_ids: set[int] | None,
    include_with_archived_blood: bool,
) -> list[tuple[int, int, int, str, str, Any, Any, int]]:
    """Return rows: user_id, engagement_id, instance_id, old_record_id, type_code, reports, report_url, ihr_report_id."""
    canonical_ihr = ReportsRepository.canonical_individual_health_report_subquery()
    query = (
        select(
            EngagementParticipant.user_id,
            Engagement.engagement_id,
            AssessmentInstance.assessment_instance_id,
            AssessmentInstance.metsights_record_id,
            AssessmentPackage.assessment_type_code,
            canonical_ihr.c.reports,
            canonical_ihr.c.report_url,
            canonical_ihr.c.report_id,
        )
        .join(Engagement, Engagement.engagement_id == EngagementParticipant.engagement_id)
        .join(
            AssessmentInstance,
            (AssessmentInstance.engagement_id == EngagementParticipant.engagement_id)
            & (AssessmentInstance.user_id == EngagementParticipant.user_id),
        )
        .join(AssessmentPackage, AssessmentPackage.package_id == AssessmentInstance.package_id)
        .outerjoin(
            canonical_ihr,
            canonical_ihr.c.assessment_instance_id == AssessmentInstance.assessment_instance_id,
        )
        .where(Engagement.engagement_id == engagement_id)
        .where(AssessmentPackage.assessment_type_code.in_(tuple(_PRO_BASIC_TYPE_CODES)))
        .where(AssessmentInstance.metsights_record_id.isnot(None))
        .where(AssessmentInstance.metsights_record_id != "")
    )
    if user_ids is not None:
        if not user_ids:
            return []
        query = query.where(EngagementParticipant.user_id.in_(user_ids))

    result = await db.execute(query)
    rows: list[tuple[int, int, int, str, str, Any, Any, int]] = []
    for row in result.all():
        user_id, eng_id, instance_id, record_id, type_code, reports, report_url, ihr_id = row
        if not _bioai_report_data_complete(reports, report_url):
            continue
        if not include_with_archived_blood:
            if await has_archived_diagnostic_blood_report(
                db,
                user_id=int(user_id),
                engagement_id=int(eng_id),
            ):
                continue
        rows.append(
            (
                int(user_id),
                int(eng_id),
                int(instance_id),
                (record_id or "").strip(),
                (type_code or "").strip(),
                reports,
                report_url,
                int(ihr_id) if ihr_id is not None else 0,
            )
        )
    return rows


async def _count_responses_for_categories(
    db: AsyncSession,
    *,
    questionnaire_repo: QuestionnaireRepository,
    assessment_instance_id: int,
    category_keys: list[str],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key in category_keys:
        category = await questionnaire_repo.get_category_by_key(db, category_key=key)
        if category is None:
            counts[key] = 0
            continue
        responses = await questionnaire_repo.list_responses_for_instance(
            db,
            assessment_instance_id=assessment_instance_id,
            category_id=int(category.category_id),
        )
        counts[key] = len(responses)
    return counts


async def remediate_bad_bioai_batch(
    db: AsyncSession,
    *,
    engagement_id: int,
    metsights_service: MetsightsService,
    sync_service: MetsightsSyncService,
    dry_run: bool = False,
    user_ids: set[int] | None = None,
    include_with_archived_blood: bool = False,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run bad-batch remediation for one engagement."""
    questionnaire_repo = QuestionnaireRepository()
    assessments_repo = AssessmentsRepository()
    reports_repo = ReportsRepository()

    blood_category = await questionnaire_repo.get_category_by_key(
        db,
        category_key=BLOOD_PARAMETER_CATEGORY_KEY,
    )
    if blood_category is None:
        return {
            "engagement_id": engagement_id,
            "matched": 0,
            "remediated": 0,
            "skipped": 0,
            "failed": 0,
            "dry_run": dry_run,
            "details": [{"action": "failed", "reason": "blood-parameters category not found"}],
        }
    blood_category_id = int(blood_category.category_id)

    primary_package_id = await _load_engagement_primary_package_id(db, engagement_id)
    if primary_package_id is None:
        return {
            "engagement_id": engagement_id,
            "matched": 0,
            "remediated": 0,
            "skipped": 0,
            "failed": 0,
            "dry_run": dry_run,
            "details": [{"action": "failed", "reason": "engagement not found or missing assessment_package_id"}],
        }

    participants = await _select_bad_batch_rows(
        db,
        engagement_id=engagement_id,
        user_ids=user_ids,
        include_with_archived_blood=include_with_archived_blood,
    )
    matched = len(participants)
    remediated = 0
    skipped = 0
    failed = 0
    details: list[dict[str, Any]] = []

    def _report(done: int) -> None:
        if on_progress is not None:
            on_progress(done, matched, remediated, skipped, failed)

    _report(0)

    for index, row in enumerate(participants, start=1):
        user_id, eng_id, instance_id, old_record_id, type_code, _reports, _report_url, ihr_report_id = row
        push_categories = categories_for_type_code(type_code)
        detail_base = {
            "user_id": user_id,
            "engagement_id": eng_id,
            "assessment_instance_id": instance_id,
            "old_metsights_record_id": old_record_id,
        }

        try:
            if dry_run:
                response_counts = await _count_responses_for_categories(
                    db,
                    questionnaire_repo=questionnaire_repo,
                    assessment_instance_id=instance_id,
                    category_keys=push_categories,
                )
                details.append({
                    **detail_base,
                    "action": "dry_run",
                    "reason": "would remediate: delete blood-parameters, clear IHR, new record, push categories",
                    "would_push_categories": push_categories,
                    "local_response_counts": response_counts,
                })
                skipped += 1
                _report(index)
                continue

            deleted_qr = await questionnaire_repo.delete_responses_for_instance_category(
                db,
                assessment_instance_id=instance_id,
                category_id=blood_category_id,
            )
            deleted_progress = await assessments_repo.delete_category_progress_for_instance_category(
                db,
                assessment_instance_id=instance_id,
                category_id=blood_category_id,
            )

            ihr: IndividualHealthReport | None = None
            if ihr_report_id:
                ihr = await db.get(IndividualHealthReport, ihr_report_id)
            if ihr is None:
                ihr = await reports_repo.get_individual_report_by_assessment(
                    db,
                    assessment_instance_id=instance_id,
                )
            if ihr is not None:
                ihr.reports = None
                ihr.report_url = None
                db.add(ihr)

            user = await db.get(User, user_id)
            package = await db.get(AssessmentPackage, primary_package_id)
            profile_id = (getattr(user, "metsights_profile_id", None) or "").strip() if user else ""
            subscription_id = (getattr(package, "subscription_id", None) or "").strip() if package else ""
            if not profile_id or not subscription_id:
                await db.rollback()
                failed += 1
                details.append({
                    **detail_base,
                    "action": "failed",
                    "reason": "missing metsights profile or primary package subscription",
                    "deleted_blood_responses": deleted_qr,
                    "deleted_blood_progress": deleted_progress,
                })
                _report(index)
                continue

            await release_request_transaction(db)
            try:
                new_rid = await metsights_service.create_record_for_profile(
                    profile_id=profile_id,
                    subscription_id=subscription_id,
                )
            except Exception as exc:
                await db.rollback()
                failed += 1
                logger.warning(
                    "MetSights record create failed user=%s instance=%s: %s",
                    user_id,
                    instance_id,
                    exc,
                )
                details.append({
                    **detail_base,
                    "action": "failed",
                    "reason": f"metsights create_record failed: {str(exc)[:120]}",
                })
                _report(index)
                continue

            new_rid = (new_rid or "").strip()
            if not new_rid:
                await db.rollback()
                failed += 1
                details.append({
                    **detail_base,
                    "action": "failed",
                    "reason": "metsights create_record returned empty id",
                })
                _report(index)
                continue

            await assessments_repo.set_metsights_record_id(
                db,
                assessment_instance_id=instance_id,
                metsights_record_id=new_rid,
            )
            participant = await get_participant_for_user_engagement(
                db,
                user_id=user_id,
                engagement_id=eng_id,
            )
            if participant is not None:
                participant.is_primary_record_id_synced = True
                db.add(participant)

            push_summary: dict[str, Any] = {}
            push_error: str | None = None
            try:
                push_summary = await sync_service.push_questionnaire_for_instance(
                    db,
                    assessment_instance_id=instance_id,
                    categories=push_categories or None,
                )
            except Exception as exc:
                push_error = str(exc)[:200]
                logger.warning(
                    "Questionnaire push failed user=%s instance=%s: %s",
                    user_id,
                    instance_id,
                    exc,
                )

            await db.commit()
            remediated += 1
            details.append({
                **detail_base,
                "action": "remediated",
                "new_metsights_record_id": new_rid,
                "deleted_blood_responses": deleted_qr,
                "deleted_blood_progress": deleted_progress,
                "push_categories": push_categories,
                "push_summary": push_summary,
                "push_error": push_error,
            })
        except Exception as exc:
            await db.rollback()
            failed += 1
            logger.exception(
                "Remediate failed user=%s engagement=%s: %s",
                user_id,
                eng_id,
                exc,
            )
            details.append({
                **detail_base,
                "action": "failed",
                "reason": str(exc)[:200],
            })

        _report(index)

    return {
        "engagement_id": engagement_id,
        "matched": matched,
        "remediated": remediated,
        "skipped": skipped,
        "failed": failed,
        "dry_run": dry_run,
        "primary_package_id": primary_package_id,
        "details": details,
    }
