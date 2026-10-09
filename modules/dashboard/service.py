"""Admin dashboard overview aggregate (Action Center bootstrap)."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.dashboard.operations_snapshot import (
    build_dashboard_participant_issues_block,
    build_operations_snapshot,
    empty_operations_snapshot,
)
from modules.employee.service import EmployeeContext
from modules.payments.models import Booking
from modules.engagements.blood_booking_enums import BloodBookingStatus
from modules.engagements.models import Engagement, EngagementParticipant, ParticipantBloodBooking
from modules.experts.models import ConsultationBooking
from modules.notifications.models import Notification
from modules.support.models import SupportTicket
from modules.users.repository import UsersRepository

logger = logging.getLogger(__name__)

# Keep below typical reverse-proxy read timeouts (often 60s).
DASHBOARD_OPERATIONS_TIMEOUT_SECONDS = 50.0


async def _operations_for_overview(db: AsyncSession, *, employee: EmployeeContext) -> dict:
    try:
        return await asyncio.wait_for(
            build_operations_snapshot(db, employee=employee),
            timeout=DASHBOARD_OPERATIONS_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning("dashboard overview: operations snapshot timed out after %ss", DASHBOARD_OPERATIONS_TIMEOUT_SECONDS)
        return empty_operations_snapshot()
    except Exception:
        logger.exception("dashboard overview: operations snapshot failed")
        return empty_operations_snapshot()


async def _participant_issues_for_overview(
    db: AsyncSession,
    *,
    employee: EmployeeContext,
) -> tuple[list[dict], dict | None]:
    try:
        return await asyncio.wait_for(
            build_dashboard_participant_issues_block(db, employee=employee),
            timeout=DASHBOARD_OPERATIONS_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning(
            "dashboard overview: participant issue summary timed out after %ss",
            DASHBOARD_OPERATIONS_TIMEOUT_SECONDS,
        )
        return [], None
    except Exception:
        logger.exception("dashboard overview: participant issue summary failed")
        return [], None


def _year_date_bounds(year: int) -> tuple[date, date]:
    return date(year, 1, 1), date(year + 1, 1, 1)


async def year_stats_payload(db: AsyncSession, *, year: int) -> dict:
    blood_start, blood_end = _year_date_bounds(year)
    consult_start, consult_end = _year_date_bounds(year)

    blood_total = (
        await db.execute(
            select(func.count())
            .select_from(ParticipantBloodBooking)
            .where(ParticipantBloodBooking.collection_date.is_not(None))
            .where(ParticipantBloodBooking.collection_date >= blood_start)
            .where(ParticipantBloodBooking.collection_date < blood_end)
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
            .where(ConsultationBooking.consultation_date >= consult_start)
            .where(ConsultationBooking.consultation_date < consult_end)
            .group_by(ConsultationBooking.expert_type)
            .order_by(func.count().desc(), ConsultationBooking.expert_type.asc())
        )
    ).all()

    by_expert = [{"expert_type": row.expert_type, "count": int(row.count)} for row in consultation_rows]
    consultations_total = sum(item["count"] for item in by_expert)

    year_set: set[int] = {date.today().year}
    for (collection_date,) in (
        await db.execute(
            select(func.distinct(func.date_part("year", ParticipantBloodBooking.collection_date))).where(
                ParticipantBloodBooking.collection_date.is_not(None)
            )
        )
    ).all():
        if collection_date is not None:
            year_set.add(int(collection_date))
    for (consultation_date,) in (
        await db.execute(
            select(func.distinct(func.date_part("year", ConsultationBooking.consultation_date))).where(
                ConsultationBooking.consultation_date.is_not(None)
            )
        )
    ).all():
        if consultation_date is not None:
            year_set.add(int(consultation_date))

    return {
        "year": year,
        "blood_collection_total": int(blood_total or 0),
        "consultations_total": consultations_total,
        "consultations_by_expert_type": by_expert,
        "available_years": sorted(year_set, reverse=True),
    }


async def _users_overview(db: AsyncSession) -> dict:
    users_repo = UsersRepository()
    total, active, year_counts = await asyncio.gather(
        users_repo.count_users(db),
        users_repo.count_users(db, status="active"),
        users_repo.count_users_created_by_year(db),
    )
    yearly_totals: list[dict] = []
    if year_counts:
        by_year = dict(year_counts)
        running = 0
        for yr in range(min(by_year), max(by_year) + 1):
            added = by_year.get(yr, 0)
            running += added
            yearly_totals.append({"year": yr, "new_users": added, "total_users": running})
    elif total > 0:
        yearly_totals.append(
            {"year": date.today().year, "new_users": total, "total_users": total}
        )

    monthly_totals: list[dict] = []
    if len(yearly_totals) == 1:
        chart_year = yearly_totals[0]["year"]
        month_counts = await users_repo.count_users_created_by_month(db, year=chart_year)
        if month_counts:
            by_month = dict(month_counts)
            running = 0
            for month in range(1, 13):
                added = by_month.get(month, 0)
                running += added
                monthly_totals.append(
                    {
                        "year": chart_year,
                        "month": month,
                        "new_users": added,
                        "total_users": running,
                    }
                )

    return {
        "total_users": total,
        "active_users": active,
        "yearly_totals": yearly_totals,
        "monthly_totals": monthly_totals,
    }


async def _participant_stats(db: AsyncSession) -> int:
    total = (
        await db.execute(
            select(func.count())
            .select_from(EngagementParticipant)
            .join(Engagement, Engagement.engagement_id == EngagementParticipant.engagement_id)
            .where(Engagement.status.in_(("running", "scheduled")))
        )
    ).scalar_one()
    return int(total or 0)


async def booking_status_totals(db: AsyncSession) -> dict[str, int]:
    rows = (
        await db.execute(
            select(Booking.status, func.count())
            .select_from(Booking)
            .where(Booking.status.in_(("pending", "confirmed", "failed", "released")))
            .group_by(Booking.status)
        )
    ).all()
    out = {status: 0 for status in ("pending", "confirmed", "failed", "released")}
    for status, count in rows:
        out[str(status)] = int(count or 0)
    return out


async def ticket_status_counts(db: AsyncSession) -> dict[str, int]:
    from db.column_types import STATUS_SUPPORT_TICKET

    code_to_label = {code: label for label, code in STATUS_SUPPORT_TICKET.items()}
    rows = (
        await db.execute(
            select(SupportTicket.status, func.count())
            .select_from(SupportTicket)
            .group_by(SupportTicket.status)
        )
    ).all()
    out = {status: 0 for status in ("open", "resolved", "closed")}
    for status, count in rows:
        if isinstance(status, int):
            label = code_to_label.get(status)
        else:
            label = str(status or "").strip().lower()
        if label in out:
            out[label] += int(count or 0)
    return out


async def _failed_notifications_count(db: AsyncSession) -> int:
    count = (
        await db.execute(
            select(func.count()).select_from(Notification).where(Notification.status == "failed")
        )
    ).scalar_one()
    return int(count or 0)


async def build_dashboard_overview(db: AsyncSession, *, employee: EmployeeContext) -> dict:
    """Single read snapshot for admin Action Center (first page only)."""
    year = date.today().year
    (
        year_stats,
        users,
        engagement_participants_total,
        payment_status_totals,
        ticket_counts,
        failed_notifications_count,
        operations,
        participant_issues_block,
    ) = await asyncio.gather(
        year_stats_payload(db, year=year),
        _users_overview(db),
        _participant_stats(db),
        booking_status_totals(db),
        ticket_status_counts(db),
        _failed_notifications_count(db),
        _operations_for_overview(db, employee=employee),
        _participant_issues_for_overview(db, employee=employee),
    )

    participant_issues, participant_issue_summary = participant_issues_block
    operations["participant_issues"] = participant_issues
    operations["participant_issue_summary"] = participant_issue_summary

    return {
        "year_stats": year_stats,
        "users": users,
        "engagement_participants_total": engagement_participants_total,
        "payment_status_totals": {
            "pending": payment_status_totals.get("pending", 0),
            "confirmed": payment_status_totals.get("confirmed", 0),
            "cancelled": payment_status_totals.get("failed", 0) + payment_status_totals.get("released", 0),
        },
        "ticket_counts": ticket_counts,
        "failed_notifications_count": failed_notifications_count,
        "operations": operations,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
