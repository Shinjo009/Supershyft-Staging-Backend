"""Dashboard year-stats for admin Action Center KPI cards."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.responses import success_response
from db.session import get_db
from modules.employee.dependencies import get_current_employee
from modules.employee.service import EmployeeContext
from modules.engagements.blood_booking_enums import BloodBookingStatus
from modules.engagements.models import Engagement, EngagementParticipant, ParticipantBloodBooking
from modules.experts.models import ConsultationBooking

router = APIRouter(prefix="/admin/dashboard", tags=["dashboard"])


@router.get("/year-stats")
async def get_year_stats(
    year: int = Query(..., ge=2000, le=2100),
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
):
    del employee  # auth gate only

    blood_total = (
        await db.execute(
            select(func.count())
            .select_from(ParticipantBloodBooking)
            .where(ParticipantBloodBooking.collection_date.is_not(None))
            .where(extract("year", ParticipantBloodBooking.collection_date) == year)
            .where(ParticipantBloodBooking.status == BloodBookingStatus.active.value)
        )
    ).scalar_one()

    consultation_rows = (
        await db.execute(
            select(
                ConsultationBooking.expert_type,
                func.count().label("count"),
            )
            .where(ConsultationBooking.consultation_date.is_not(None))
            .where(extract("year", ConsultationBooking.consultation_date) == year)
            .group_by(ConsultationBooking.expert_type)
            .order_by(func.count().desc(), ConsultationBooking.expert_type.asc())
        )
    ).all()

    by_expert = [
        {"expert_type": row.expert_type, "count": int(row.count)}
        for row in consultation_rows
    ]
    consultations_total = sum(item["count"] for item in by_expert)

    year_set: set[int] = {date.today().year}
    for (y,) in (
        await db.execute(
            select(func.distinct(extract("year", ParticipantBloodBooking.collection_date))).where(
                ParticipantBloodBooking.collection_date.is_not(None)
            )
        )
    ).all():
        if y is not None:
            year_set.add(int(y))
    for (y,) in (
        await db.execute(
            select(func.distinct(extract("year", ConsultationBooking.consultation_date))).where(
                ConsultationBooking.consultation_date.is_not(None)
            )
        )
    ).all():
        if y is not None:
            year_set.add(int(y))

    return success_response(
        {
            "year": year,
            "blood_collection_total": int(blood_total or 0),
            "consultations_total": consultations_total,
            "consultations_by_expert_type": by_expert,
            "available_years": sorted(year_set, reverse=True),
        }
    )


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
