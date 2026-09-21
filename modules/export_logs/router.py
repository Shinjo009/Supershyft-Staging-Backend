"""HTTP routes for staff data-export audit logs."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from common.responses import success_response
from core.exceptions import AppError
from core.network import get_client_ip
from db.session import get_db
from modules.employee.dependencies import get_current_employee
from modules.employee.service import EmployeeContext
from modules.export_logs.dependencies import (
    ExportActor,
    get_export_actor,
    get_export_logs_service,
)
from modules.export_logs.schemas import ExportLogCreateRequest
from modules.export_logs.service import ExportLogsService


router = APIRouter(tags=["export-logs"])


@router.post("/export-logs")
async def create_export_log(
    payload: ExportLogCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: ExportActor = Depends(get_export_actor),
    service: ExportLogsService = Depends(get_export_logs_service),
):
    row = await service.create_log(
        db,
        payload=payload,
        employee_id=actor.employee_id,
        partner_id=actor.partner_id,
        actor_name=actor.actor_name,
        actor_role=actor.actor_role,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent", "unknown"),
    )
    await db.commit()
    return success_response({"export_log_id": row.export_log_id})


@router.get("/employees/export-logs")
async def list_export_logs(
    page: int = 1,
    limit: int = 25,
    search: str | None = None,
    employee_id: int | None = None,
    export_type: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    _employee: EmployeeContext = Depends(get_current_employee),
    service: ExportLogsService = Depends(get_export_logs_service),
):
    if page < 1 or limit < 1 or limit > 100:
        raise AppError(status_code=400, error_code="INVALID_INPUT", message="Invalid request")

    items, total = await service.list_logs(
        db,
        page=page,
        limit=limit,
        search=(search or "").strip() or None,
        employee_id=employee_id,
        export_type=(export_type or "").strip() or None,
        created_from=created_from,
        created_to=created_to,
    )
    return success_response(items, meta={"page": page, "limit": limit, "total": total})
