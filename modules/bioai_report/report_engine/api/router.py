"""HTTP routes that return assembled BioReport JSON (no PDF).

Frontend contract — single call, single input:

    GET /bioai-report/{assessment_instance_id}

Accessible to the user who owns the assessment instance, and to admin
employees. The backend resolves the assessment to a user, builds the Bio-AI
report from the user's latest stored IHR, and attaches historical trends cut
off at the requested assessment date. This route does not call MetSights.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import get_optional_user
from core.exceptions import AppError
from db.session import get_db
from modules.assessments.repository import AssessmentsRepository
from modules.bioai_report.report_engine.api.dependencies import (
    get_bioai_trend_service,
    get_bioreport_service,
)
from modules.bioai_report.report_engine.exceptions import KnowledgeBaseError, ReportEngineError
from modules.bioai_report.report_engine.services.report_service import BioReportService
from modules.bioai_report.report_engine.services.trend_service import BioAITrendService
from modules.employee.access_control import ensure_admin
from modules.employee.dependencies import get_optional_employee
from modules.employee.service import EmployeeContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bioai-report", tags=["bioai-report"])


async def _authorize_bioai_report_read(
    db: AsyncSession,
    *,
    assessment_instance_id: int,
    user,
    employee: EmployeeContext | None,
) -> None:
    """Allow the instance owner (user JWT) or any admin (employee JWT)."""
    if employee is not None:
        ensure_admin(employee)
        return
    if user is None:
        raise AppError(
            status_code=401,
            error_code="AUTH_FAILED",
            message="Authentication failed",
        )
    instance = await AssessmentsRepository().get_instance_by_id(
        db,
        assessment_instance_id=assessment_instance_id,
    )
    if instance is None or int(instance.user_id) != int(user.user_id):
        raise AppError(
            status_code=404,
            error_code="ASSESSMENT_NOT_FOUND",
            message="Assessment does not exist",
        )


@router.get("/{assessment_instance_id}")
async def get_bioreport_content(
    assessment_instance_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_optional_user),
    employee: EmployeeContext | None = Depends(get_optional_employee),
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

    await _authorize_bioai_report_read(
        db,
        assessment_instance_id=int(assessment_instance_id),
        user=current_user,
        employee=employee,
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
