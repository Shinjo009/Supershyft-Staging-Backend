"""Vitals gate before MetSights Bio AI report fetch (types 1 and 2)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from modules.assessments.service import AssessmentsService
    from modules.metsights.sync_service import MetsightsSyncService

logger = logging.getLogger(__name__)

_BIO_AI_TYPE_CODES = frozenset({"1", "2"})


async def ensure_vitals_before_bio_ai_generation(
    db: AsyncSession,
    *,
    assessments_service: AssessmentsService,
    sync_service: MetsightsSyncService,
    user_id: int,
    engagement_id: int,
    assessment_instance_id: int,
    type_code: str,
    details: list[dict[str, Any]] | None = None,
) -> bool:
    """Draft 120/80 BP when missing, push vitals to MetSights. Required before ``get_report``."""
    tc = (type_code or "").strip()
    if tc not in _BIO_AI_TYPE_CODES:
        return True

    detail_list = details if details is not None else []

    try:
        if await assessments_service.is_vitals_blood_pressure_missing(
            db,
            assessment_instance_id=assessment_instance_id,
        ):
            draft_result = await assessments_service.draft_vitals_blood_pressure_fallbacks(
                db,
                user_id=user_id,
                assessment_instance_id=assessment_instance_id,
            )
            await db.commit()
            drafted_count = int(draft_result.get("responses_drafted") or 0)
            detail_list.append({
                "user_id": user_id,
                "engagement_id": engagement_id,
                "action": "drafted",
                "reason": (
                    f"applied default BP 120/80 ({drafted_count} vitals responses drafted)"
                ),
            })

        push_result = await sync_service._push_category_to_metsights(
            db,
            assessment_instance_id=assessment_instance_id,
            user_id=user_id,
            category_key="vitals",
        )
        await db.commit()
        fields_count = len(push_result.get("fields_pushed") or [])
        push_status = (push_result.get("status") or "").strip().lower()
        if push_status == "skipped" or fields_count == 0:
            detail_list.append({
                "user_id": user_id,
                "engagement_id": engagement_id,
                "action": "skipped",
                "reason": (
                    "vitals not ready for Bio AI: no committed answers to push "
                    f"(status={push_status or 'empty'})"
                ),
            })
            return False
        detail_list.append({
            "user_id": user_id,
            "engagement_id": engagement_id,
            "action": "pushed",
            "reason": f"pushed vitals to MetSights ({fields_count} fields)",
        })
        return True
    except Exception as exc:
        await db.rollback()
        logger.warning(
            "BioAI vitals gate failed for user=%s instance=%s: %s",
            user_id,
            assessment_instance_id,
            exc,
        )
        detail_list.append({
            "user_id": user_id,
            "engagement_id": engagement_id,
            "action": "skipped",
            "reason": f"vitals not ready for Bio AI generation: {str(exc)[:120]}",
        })
        return False