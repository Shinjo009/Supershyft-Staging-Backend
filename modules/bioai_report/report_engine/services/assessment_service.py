"""Fetch assessment JSON for a MetSights record_id.

Upstream source (production):

    GET {METSIGHTS_BASE_URL}/external/reports/metsights/{record_id}/

(FitPrint type ``7`` uses ``/external/reports/fitness/{record_id}/``.)

That GET materializes the report on MetSights; use it only for intentional fetch
(load Bio AI, regenerate, resolver). Existence checks must use record ``has_report``.

This is step 1 of the Bio-AI pipeline. The engine never accepts assessment
JSON from the frontend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from modules.bioai_report.report_engine.models.assessment import AssessmentPayload
from modules.bioai_report.report_engine.utils.assessment_normalizer import normalize_assessment
from modules.metsights.bio_ai_vitals_gate import ensure_vitals_before_bio_ai_generation
from modules.metsights.service import MetsightsService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from modules.assessments.service import AssessmentsService
    from modules.metsights.sync_service import MetsightsSyncService


class AssessmentFetchService:
    """Retrieve assessment data via the existing Metsights reports API."""

    def __init__(self, metsights_service: MetsightsService) -> None:
        self._metsights = metsights_service

    async def fetch_raw(
        self,
        *,
        record_id: str,
        assessment_type_code: str | None = None,
        db: "AsyncSession | None" = None,
        user_id: int | None = None,
        engagement_id: int | None = None,
        assessment_instance_id: int | None = None,
        assessments_service: "AssessmentsService | None" = None,
        sync_service: "MetsightsSyncService | None" = None,
    ) -> dict[str, Any]:
        """Fetch the raw MetSights report payload for ``record_id``.

        When ``db`` and assessment context are provided for types 1/2, vitals are
        ensured on MetSights before GET report. Record-only calls must pre-push vitals.
        """
        type_code = (assessment_type_code or "").strip()
        if (
            db is not None
            and type_code in ("1", "2")
            and assessment_instance_id is not None
            and user_id is not None
            and engagement_id is not None
        ):
            if assessments_service is None:
                from modules.assessments.dependencies import get_assessments_service

                assessments_service = get_assessments_service()
            if sync_service is None:
                from modules.metsights.dependencies import get_metsights_sync_service

                sync_service = get_metsights_sync_service()
            vitals_ready = await ensure_vitals_before_bio_ai_generation(
                db,
                assessments_service=assessments_service,
                sync_service=sync_service,
                user_id=int(user_id),
                engagement_id=int(engagement_id),
                assessment_instance_id=int(assessment_instance_id),
                type_code=type_code,
            )
            if not vitals_ready:
                raise RuntimeError("Vitals required for Bio AI generation")

        data = await self._metsights.get_report(
            record_id=record_id,
            assessment_type_code=assessment_type_code,
        )
        if not isinstance(data, dict):
            return {"data": data}
        return data

    async def fetch(
        self,
        *,
        record_id: str,
        assessment_type_code: str | None = None,
    ) -> AssessmentPayload:
        """Fetch and normalize assessment JSON for report assembly."""
        raw = await self.fetch_raw(
            record_id=record_id,
            assessment_type_code=assessment_type_code,
        )
        return normalize_assessment(raw, record_id=record_id)
