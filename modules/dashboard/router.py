"""Dashboard year-stats for admin Action Center KPI cards."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.responses import success_response
from db.session import get_db
from modules.employee.dependencies import get_current_employee
from modules.employee.service import EmployeeContext
from modules.dashboard.service import build_dashboard_overview, year_stats_payload
from modules.engagements.models import Engagement, EngagementParticipant

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
