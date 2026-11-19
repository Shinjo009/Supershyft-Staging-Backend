"""Fetch MetSights Bio AI report JSON (with vitals gate for types 1 and 2)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppError
from modules.audit.cron_sync_logging import tracked_integration_call
from modules.metsights.bio_ai_vitals_gate import ensure_vitals_before_bio_ai_generation
from modules.metsights.service import MetsightsService

if TYPE_CHECKING:
    from modules.assessments.service import AssessmentsService
    from modules.metsights.sync_service import MetsightsSyncService

logger = logging.getLogger(__name__)

_PRO_BASIC_TYPE_CODES = frozenset({"1", "2"})


def metsights_bio_ai_report_url(
    *,
    record_id: str,
    assessment_type_code: str,
    pdf: bool = False,
) -> str:
    from modules.metsights.integration_logging import metsights_api_url

    branch = "fitness" if assessment_type_code == "7" else "metsights"
    path = f"reports/{branch}/{record_id}"
    if pdf:
        path = f"{path}/pdf"
    return metsights_api_url(path)


async def fetch_metsights_report_json(
    db: AsyncSession,
    *,
    metsights_service: MetsightsService,
    record_id: str,
    type_code: str,
    engagement_id: int,
    user_id: int,
    assessment_instance_id: int | None = None,
    assessments_service: AssessmentsService | None = None,
    sync_service: MetsightsSyncService | None = None,
    details: list[dict[str, Any]] | None = None,
) -> tuple[Any | None, bool]:
    """Return ``(report, record_incomplete)``.

    ``record_incomplete`` is true when MetSights answers 404. That response means
    the record is missing or not complete, so result generation cannot start.
    """
    record_incomplete = False

    if (
        (type_code or "").strip() in _PRO_BASIC_TYPE_CODES
        and assessment_instance_id is not None
        and assessments_service is not None
        and sync_service is not None
    ):
        vitals_ready = await ensure_vitals_before_bio_ai_generation(
            db,
            assessments_service=assessments_service,
            sync_service=sync_service,
            user_id=user_id,
            engagement_id=engagement_id,
            assessment_instance_id=assessment_instance_id,
            type_code=type_code,
            details=details,
        )
        if not vitals_ready:
            return None, False

    async def _load() -> Any:
        nonlocal record_incomplete
        try:
            return await metsights_service.get_report(
                record_id=record_id,
                assessment_type_code=type_code,
            )
        except AppError as exc:
            if exc.error_code == "REPORT_NOT_FOUND":
                record_incomplete = True
            raise

    report_data = await tracked_integration_call(
        db,
        provider="metsights",
        api_url=metsights_bio_ai_report_url(
            record_id=record_id,
            assessment_type_code=type_code,
        ),
        engagement_id=engagement_id,
        user_id=user_id,
        request_payload={
            "record_id": record_id,
            "assessment_type_code": type_code,
        },
        operation=_load,
        reraise=False,
    )
    if report_data is not None and report_data:
        return report_data, False
    if report_data is None:
        logger.warning(
            "MetSights get_report failed for record=%s incomplete=%s",
            record_id,
            record_incomplete,
        )
    return None, record_incomplete


# Backward-compatible alias for existing imports
_fetch_metsights_report_json = fetch_metsights_report_json