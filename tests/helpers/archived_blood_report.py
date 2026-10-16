"""Seed archived diagnostic blood PDF on participant blood bookings for tests."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from modules.engagements.blood_booking_enums import BloodBookingStatus
from modules.engagements.models import EngagementParticipant, ParticipantBloodBooking


def default_archived_blood_report_url() -> str:
    base = (settings.BLOOD_REPORTS_BASE_URL or "https://supershyft.com/reports").rstrip("/")
    return f"{base}/AbCdEfGhIjKlMnOp.pdf"


async def seed_archived_diagnostic_blood_report(
    session: AsyncSession,
    *,
    user_id: int,
    engagement_id: int,
    diagnostic_report_url: str | None = None,
    collection_date: date | None = None,
) -> ParticipantBloodBooking:
    """Ensure current blood booking row has an archived partner PDF URL."""
    participant = (
        await session.execute(
            select(EngagementParticipant)
            .where(EngagementParticipant.user_id == user_id)
            .where(EngagementParticipant.engagement_id == engagement_id)
            .order_by(EngagementParticipant.engagement_participant_id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if participant is None:
        raise ValueError(
            f"No engagement participant for user_id={user_id} engagement_id={engagement_id}"
        )

    blood_row = (
        await session.execute(
            select(ParticipantBloodBooking).where(
                ParticipantBloodBooking.engagement_participant_id
                == participant.engagement_participant_id
            )
        )
    ).scalars().first()

    coll_date = collection_date or (date.today() - timedelta(days=1))
    url = diagnostic_report_url or default_archived_blood_report_url()

    if blood_row is None:
        blood_row = ParticipantBloodBooking(
            engagement_participant_id=participant.engagement_participant_id,
            collection_date=coll_date,
            status=BloodBookingStatus.active.value,
            diagnostic_report_url=url,
        )
        session.add(blood_row)
    else:
        blood_row.collection_date = coll_date
        blood_row.status = BloodBookingStatus.active.value
        blood_row.diagnostic_report_url = url

    await session.flush()
    await session.commit()
    return blood_row
