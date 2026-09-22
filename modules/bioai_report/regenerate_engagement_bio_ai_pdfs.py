"""Regenerate Bio AI PDFs at existing slugs for one engagement.

Calls ``regenerate_permanent_bio_ai_report_url`` for each participant on the
engagement's primary assessment that already has a bio-ai-reports permanent URL.
External calls are logged to ``integration_sync_logs`` via ``tracked_integration_call``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.assessments.models import AssessmentInstance, AssessmentPackage
from modules.bioai_report.pdf_registration import (
    extract_slug_from_report_url,
    is_bio_ai_assessment_type,
    regenerate_permanent_bio_ai_report_url,
    resolve_canonical_bio_ai_report_url,
)
from modules.engagements.models import Engagement, EngagementParticipant
from modules.reports.repository import ReportsRepository

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, int, int, int], None]


async def _get_engagement_pdf_regenerate_candidates(
    db: AsyncSession,
    *,
    engagement_id: int,
) -> list[tuple]:
    """Participants on the primary assessment with an existing bio-ai-reports URL."""
    canonical_ihr = ReportsRepository.canonical_individual_health_report_subquery()
    query = (
        select(
            EngagementParticipant.user_id,
            Engagement.engagement_id,
            AssessmentInstance.assessment_instance_id,
            AssessmentPackage.assessment_type_code,
            canonical_ihr.c.report_url,
        )
        .join(Engagement, Engagement.engagement_id == EngagementParticipant.engagement_id)
        .join(
            AssessmentInstance,
            (AssessmentInstance.engagement_id == EngagementParticipant.engagement_id)
            & (AssessmentInstance.user_id == EngagementParticipant.user_id)
            & (AssessmentInstance.package_id == Engagement.assessment_package_id),
        )
        .join(AssessmentPackage, AssessmentPackage.package_id == AssessmentInstance.package_id)
        .join(
            canonical_ihr,
            canonical_ihr.c.assessment_instance_id == AssessmentInstance.assessment_instance_id,
        )
        .where(Engagement.engagement_id == engagement_id)
        .where(Engagement.assessment_package_id.isnot(None))
        .where(canonical_ihr.c.report_url.isnot(None))
        .where(canonical_ihr.c.report_url != "")
        .order_by(EngagementParticipant.user_id.asc())
    )
    result = await db.execute(query)
    return result.all()


async def regenerate_engagement_bio_ai_pdfs(
    db: AsyncSession,
    *,
    engagement_id: int,
    dry_run: bool = False,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Regenerate Bio AI PDFs at existing slugs for one engagement."""
    participants = await _get_engagement_pdf_regenerate_candidates(
        db,
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
                type_code,
                existing_report_url,
            ) = row

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

            canonical_report_url = await resolve_canonical_bio_ai_report_url(
                db,
                user_id=user_id,
                engagement_id=row_engagement_id,
                assessment_instance_id=instance_id,
                report_url=report_url,
            )
            if not canonical_report_url:
                skipped += 1
                details.append({
                    "user_id": user_id,
                    "engagement_id": row_engagement_id,
                    "action": "skipped",
                    "reason": "no bio-ai-reports permanent URL found for participant",
                })
                continue

            slug = extract_slug_from_report_url(canonical_report_url)
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
                    "reason": f"would regenerate PDF at slug={slug}",
                })
                continue

            try:
                await regenerate_permanent_bio_ai_report_url(
                    db,
                    assessment_instance_id=instance_id,
                    report_url=canonical_report_url,
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
                    "Bio AI PDF regenerate failed for user=%s engagement=%s instance=%s: %s",
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
                "reason": f"PDF regenerated at slug={slug}",
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
            logger.exception("Unexpected Bio AI PDF regenerate failure")
        finally:
            _report(index)

    return {
        "dry_run": dry_run,
        "engagement_id": engagement_id,
        "matched": matched,
        "regenerated": regenerated,
        "skipped": skipped,
        "failed": failed,
        "details": details,
    }
