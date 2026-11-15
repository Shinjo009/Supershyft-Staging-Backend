"""Dashboard year-stats and overview/operations for admin KPI cards."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.responses import success_response
from db.session import get_db
from modules.dashboard.command_period import resolve_period_bounds
from modules.dashboard.command_service import (
    failed_notifications_page,
    notification_health_counts,
    people_registered_count,
    people_registered_page,
)
from modules.dashboard.service import (
    build_dashboard_operations,
    build_dashboard_overview,
    year_stats_payload,
)
from modules.employee.dependencies import get_current_employee
from modules.employee.service import EmployeeContext
from modules.engagements.models import Engagement, EngagementParticipant
from modules.notifications.dependencies import get_notifications_service
from modules.notifications.service import NotificationsService
from modules.questionnaire.dependencies import get_questionnaire_management_service
from modules.questionnaire.service import QuestionnaireService

router = APIRouter(prefix="/admin/dashboard", tags=["dashboard"])


@router.get("/year-stats")
async def get_year_stats(
    year: int = Query(..., ge=2000, le=2100),
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
):
    del employee  # auth gate only
    return success_response(await year_stats_payload(db, year=year))


@router.get("/participant-stats")
async def get_participant_stats(
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
):
    del employee  # auth gate only

    total = (
        await db.execute(
            select(func.count())
            .select_from(EngagementParticipant)
            .join(Engagement, Engagement.engagement_id == EngagementParticipant.engagement_id)
            .where(Engagement.status.in_(("running", "scheduled")))
        )
    ).scalar_one()

    return success_response({"engagement_participants_total": int(total or 0)})


@router.get("/overview")
async def get_dashboard_overview(
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
):
    payload = await build_dashboard_overview(db, employee=employee)
    return success_response(payload)


@router.get("/operations")
async def get_dashboard_operations(
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
):
    payload = await build_dashboard_operations(db, employee=employee)
    return success_response(payload)


@router.get("/command/notification-health")
async def get_command_notification_health(
    period: str = Query("this_week"),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
):
    del employee
    start, end, preset = resolve_period_bounds(
        period=period, from_date=from_date, to_date=to_date
    )
    counts = await notification_health_counts(
        db, dispatched_from=start, dispatched_to=end
    )
    return success_response(counts, meta={"period": preset})


@router.get("/command/notification-health/failed")
async def get_command_notification_health_failed(
    period: str = Query("this_week"),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
    notifications_service: NotificationsService = Depends(get_notifications_service),
):
    del employee
    start, end, preset = resolve_period_bounds(
        period=period, from_date=from_date, to_date=to_date
    )
    rows, total = await failed_notifications_page(
        db,
        notifications_service=notifications_service,
        dispatched_from=start,
        dispatched_to=end,
        page=page,
        limit=limit,
    )
    return success_response(
        rows,
        meta={"period": preset, "page": page, "limit": limit, "total": total},
    )


@router.get("/command/people-registered")
async def get_command_people_registered(
    period: str = Query("this_week"),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    include_rows: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
    questionnaire_service: QuestionnaireService = Depends(
        get_questionnaire_management_service
    ),
):
    del employee
    start, end, preset = resolve_period_bounds(
        period=period, from_date=from_date, to_date=to_date
    )
    all_time = preset == "all_time"
    if not include_rows:
        total = await people_registered_count(
            db, created_from=start, created_to=end, all_time=all_time
        )
        return success_response(
            [],
            meta={"period": preset, "page": page, "limit": limit, "total": total},
        )
    rows, total = await people_registered_page(
        db,
        created_from=start,
        created_to=end,
        all_time=all_time,
        page=page,
        limit=limit,
        questionnaire_service=questionnaire_service,
    )
    return success_response(
        rows,
        meta={"period": preset, "page": page, "limit": limit, "total": total},
    )
