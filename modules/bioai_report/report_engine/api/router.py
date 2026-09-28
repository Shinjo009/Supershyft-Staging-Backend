"""HTTP routes that return assembled BioReport JSON (no PDF).

Frontend contract — single call, single input:

    GET /bioai-report/{assessment_instance_id}

The backend resolves the assessment to a user, builds the Bio-AI report from
the user's latest stored IHR, and attaches historical trends cut off at the
requested assessment date. This route does not call MetSights and does not
perform endpoint-specific authorization.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppError
from db.session import get_db
from modules.bioai_report.report_engine.api.dependencies import (
    get_bioai_trend_service,
    get_bioreport_service,
)
from modules.bioai_report.report_engine.exceptions import KnowledgeBaseError, ReportEngineError
from modules.bioai_report.report_engine.services.report_service import BioReportService
from modules.bioai_report.report_engine.services.trend_service import BioAITrendService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bioai-report", tags=["bioai-report"])


@router.get("/{assessment_instance_id}")
async def get_bioreport_content(
    assessment_instance_id: int,
    db: AsyncSession = Depends(get_db),
    report_service: BioReportService = Depends(get_bioreport_service),
    trend_service: BioAITrendService = Depends(get_bioai_trend_service),
):
    """Return one complete BioReport for ``assessment_instance_id``.

    Pipeline (all server-side, SuperShyft DB + stored IHR):
    1. Resolve ``user_id`` from ``assessment_instances``
    2. Load the user's latest completed Basic/Pro IHR ``reports`` JSON
    3. Normalize and build the existing BioReport
    4. Enrich patient demographics from the SuperShyft user/profile
    5. Attach ``health_trends`` cut off at this assessment date
    """
    if assessment_instance_id is None:
        raise AppError(
            status_code=422,
            error_code="INVALID_STATE",
            message="assessment_instance_id is required",
        )

    try:
        report = await report_service.generate_for_assessment_instance(
            assessment_instance_id=int(assessment_instance_id),
            db=db,
        )
    except KnowledgeBaseError as exc:
        raise AppError(
            status_code=422,
            error_code="INVALID_STATE",
            message=str(exc),
        ) from exc
    except ReportEngineError as exc:
        raise AppError(
            status_code=500,
            error_code="INTERNAL_ERROR",
            message=str(exc),
        ) from exc
    except ValueError as exc:
        raise AppError(
            status_code=422,
            error_code="INVALID_STATE",
            message=str(exc),
        ) from exc

    payload = report.to_dict()
    try:
        await db.rollback()
    except Exception:
        logger.exception(
            "Bio-AI report could not reset DB session before trends for assessment_instance_id=%s",
            assessment_instance_id,
        )
    payload["health_trends"] = await trend_service.embed_for_assessment_instance(
        db,
        assessment_instance_id=int(assessment_instance_id),
        report_payload=payload,
    )
    return payload
