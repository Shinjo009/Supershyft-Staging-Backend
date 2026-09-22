"""Server health monitoring routes (admin read-only + cron metrics ingest)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from common.responses import success_response
from core.exceptions import AppError
from db.session import get_db
from modules.employee.dependencies import get_current_employee
from modules.employee.service import EmployeeContext
from modules.notifications.service import NotificationsService
from modules.server_health.dependencies import (
    get_server_health_notifications_service,
    get_server_health_service,
    require_health_api_token,
)
from modules.server_health.schemas import ServerHealthMetricsIn
from modules.server_health.service import ServerHealthService

router = APIRouter(prefix="/server-health", tags=["server-health"])


@router.get("/current")
async def get_server_health_current(
    employee: EmployeeContext = Depends(get_current_employee),
    service: ServerHealthService = Depends(get_server_health_service),
    db: AsyncSession = Depends(get_db),
):
    data = await service.get_current_status(employee, db)
    return success_response(data.model_dump() if data is not None else None)


@router.get("/history")
async def list_server_health_history(
    limit: int = 50,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    employee: EmployeeContext = Depends(get_current_employee),
    service: ServerHealthService = Depends(get_server_health_service),
):
    if limit < 1 or limit > 500:
        raise AppError(status_code=400, error_code="INVALID_INPUT", message="Invalid request")

    items, total = await service.list_history(
        employee,
        limit=limit,
        run_from=from_,
        run_to=to,
    )
    return success_response(
        [item.model_dump() for item in items],
        meta={"limit": limit, "total": total},
    )


@router.post("/metrics")
async def ingest_server_health_metrics(
    payload: ServerHealthMetricsIn,
    db: AsyncSession = Depends(get_db),
    service: ServerHealthService = Depends(get_server_health_service),
    notifications_service: NotificationsService = Depends(get_server_health_notifications_service),
    _: None = Depends(require_health_api_token),
):
    data = await service.ingest_metrics(
        db,
        payload=payload,
        notifications_service=notifications_service,
    )
    await db.commit()
    return success_response(data)
