"""Camp progress report and day-wise summary metrics for engagement overview."""

from __future__ import annotations

from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Date, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.engagements.blood_booking_enums import BloodBookingStatus
from modules.engagements.blood_bookings_repository import (
    countable_blood_booking_subquery,
    current_blood_booking_subquery,
)
from modules.engagements.models import Engagement, EngagementParticipant
from modules.engagements.slot_detail_dates import (
    enabled_blood_collection_dates,
    enabled_consultation_dates,
)
from modules.experts.models import ConsultationBooking
from modules.reports.questionnaire_kpi_completion import (
    count_questionnaire_completed_on_day,
    questionnaire_kpi_counts_for_engagement,
)

_IST = ZoneInfo("Asia/Kolkata")


async def build_progress_report(
    db: AsyncSession,
    *,
    engagement: Engagement,
    questionnaire_service: Any | None = None,
) -> dict[str, int]:
    del questionnaire_service  # KPI rules are shared with camp reports; unused here.
    engagement_id = int(engagement.engagement_id)

    total_registered = int(
        (
            await db.execute(
                select(func.count())
                .select_from(EngagementParticipant)
                .where(EngagementParticipant.engagement_id == engagement_id)
            )
        ).scalar_one()
        or 0
    )

    curr = current_blood_booking_subquery()
    has_booking_id = and_(
        curr.c.booking_id.is_not(None),
        func.btrim(curr.c.booking_id) != "",
    )
    blood_collected = int(
        (
            await db.execute(
                select(func.count())
                .select_from(curr)
                .join(
                    EngagementParticipant,
                    EngagementParticipant.engagement_participant_id
                    == curr.c.engagement_participant_id,
                )
                .where(EngagementParticipant.engagement_id == engagement_id)
                .where(curr.c.collected_at.is_not(None))
                .where(has_booking_id)
            )
        ).scalar_one()
        or 0
    )

    q_kpi = await questionnaire_kpi_counts_for_engagement(db, engagement_id=engagement_id)
    questionnaire_filled = int(q_kpi.get("filled") or 0)

    consultation_done = int(
        (
            await db.execute(
                select(func.count(func.distinct(EngagementParticipant.engagement_participant_id)))
                .select_from(ConsultationBooking)
                .join(
                    EngagementParticipant,
                    EngagementParticipant.engagement_participant_id
                    == ConsultationBooking.engagement_participant_id,
                )
                .where(EngagementParticipant.engagement_id == engagement_id)
                .where(ConsultationBooking.done.is_(True))
            )
        ).scalar_one()
        or 0
    )

    return {
        "total_registered": total_registered,
        "blood_collected": blood_collected,
        "questionnaire_filled": questionnaire_filled,
        # Placeholders until counting rules are defined.
        "blood_report_sent": 0,
        "bio_ai_report_sent": 0,
        "consultation_done": consultation_done,
    }


async def _blood_day_metrics(
    db: AsyncSession,
    *,
    engagement_id: int,
    day: date,
    filled_completion_at_by_user: dict[int, Any],
) -> dict[str, int]:
    curr = countable_blood_booking_subquery()
    is_active = curr.c.status == BloodBookingStatus.active.value
    collection_date = curr.c.collection_date
    collected_at_ist = cast(func.timezone("Asia/Kolkata", curr.c.collected_at), Date)
    has_booking_id = and_(
        curr.c.booking_id.is_not(None),
        func.btrim(curr.c.booking_id) != "",
    )

    expected = int(
        (
            await db.execute(
                select(func.count())
                .select_from(curr)
                .join(
                    EngagementParticipant,
                    EngagementParticipant.engagement_participant_id
                    == curr.c.engagement_participant_id,
                )
                .where(EngagementParticipant.engagement_id == engagement_id)
                .where(is_active)
                .where(collection_date == day)
            )
        ).scalar_one()
        or 0
    )

    sample_collected = int(
        (
            await db.execute(
                select(func.count())
                .select_from(curr)
                .join(
                    EngagementParticipant,
                    EngagementParticipant.engagement_participant_id
                    == curr.c.engagement_participant_id,
                )
                .where(EngagementParticipant.engagement_id == engagement_id)
                .where(has_booking_id)
                .where(collected_at_ist == day)
            )
        ).scalar_one()
        or 0
    )

    questionnaire_completed = count_questionnaire_completed_on_day(
        filled_completion_at_by_user=filled_completion_at_by_user,
        day=day,
    )

    return {
        "expected_collection": expected,
        "sample_collected": sample_collected,
        "questionnaire_completed": questionnaire_completed,
    }


async def _consultation_day_metrics(
    db: AsyncSession,
    *,
    engagement_id: int,
    day: date,
) -> dict[str, int]:
    done_at_ist = cast(
        func.timezone("Asia/Kolkata", ConsultationBooking.consultation_done_at),
        Date,
    )

    want = int(
        (
            await db.execute(
                select(func.count(func.distinct(EngagementParticipant.engagement_participant_id)))
                .select_from(ConsultationBooking)
                .join(
                    EngagementParticipant,
                    EngagementParticipant.engagement_participant_id
                    == ConsultationBooking.engagement_participant_id,
                )
                .where(EngagementParticipant.engagement_id == engagement_id)
                .where(ConsultationBooking.want.is_(True))
                .where(ConsultationBooking.consultation_date == day)
            )
        ).scalar_one()
        or 0
    )

    done = int(
        (
            await db.execute(
                select(func.count(func.distinct(EngagementParticipant.engagement_participant_id)))
                .select_from(ConsultationBooking)
                .join(
                    EngagementParticipant,
                    EngagementParticipant.engagement_participant_id
                    == ConsultationBooking.engagement_participant_id,
                )
                .where(EngagementParticipant.engagement_id == engagement_id)
                .where(ConsultationBooking.done.is_(True))
                .where(done_at_ist == day)
            )
        ).scalar_one()
        or 0
    )

    return {
        "consultation_want": want,
        "consultation_done": done,
    }


async def build_day_wise_summary(
    db: AsyncSession,
    *,
    engagement: Engagement,
    slot_detail: dict[str, Any] | None,
    section: str | None = None,
    date_filter: date | None = None,
    questionnaire_service: Any | None = None,
) -> dict[str, Any]:
    del questionnaire_service
    engagement_id = int(engagement.engagement_id)
    blood_dates = enabled_blood_collection_dates(slot_detail)
    consultation_dates = enabled_consultation_dates(slot_detail)

    include_blood = section in (None, "blood_collection", "both", "")
    include_consultation = section in (None, "consultation", "both", "")

    blood_by_date: dict[str, dict[str, int]] = {}
    consultation_by_date: dict[str, dict[str, int]] = {}

    filled_completion_at_by_user: dict[int, Any] = {}
    if include_blood:
        q_kpi = await questionnaire_kpi_counts_for_engagement(db, engagement_id=engagement_id)
        filled_completion_at_by_user = dict(
            q_kpi.get("filled_completion_at_by_user") or {}
        )
        days = [date_filter] if date_filter is not None else blood_dates
        for day in days:
            if day is None:
                continue
            blood_by_date[day.isoformat()] = await _blood_day_metrics(
                db,
                engagement_id=engagement_id,
                day=day,
                filled_completion_at_by_user=filled_completion_at_by_user,
            )

    if include_consultation:
        days = [date_filter] if date_filter is not None else consultation_dates
        for day in days:
            if day is None:
                continue
            consultation_by_date[day.isoformat()] = await _consultation_day_metrics(
                db,
                engagement_id=engagement_id,
                day=day,
            )

    return {
        "blood_collection_dates": [d.isoformat() for d in blood_dates],
        "consultation_dates": [d.isoformat() for d in consultation_dates],
        "blood_collection": blood_by_date,
        "consultation": consultation_by_date,
    }