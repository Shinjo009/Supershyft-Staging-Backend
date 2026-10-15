"""Shared seeds for on-site camp engagement console API tests."""

from __future__ import annotations

from datetime import date, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.engagements.models import EngagementParticipant, ParticipantBloodBooking


async def upsert_camp_participant_with_schedule(
    session: AsyncSession,
    *,
    engagement_participant_id: int,
    engagement_id: int,
    user_id: int,
    booked_by_user_id: int | None = None,
    collection_date: date | None = None,
    collection_time: time | None = None,
    booking_id: str | None = None,
    barcode: str | None = None,
) -> EngagementParticipant:
    """Create or update enrollment + current blood collection row (schedule/booking live on PBB)."""
    booked_by = booked_by_user_id if booked_by_user_id is not None else user_id
    participant = await session.get(EngagementParticipant, engagement_participant_id)
    if participant is None:
        participant = EngagementParticipant(
            engagement_participant_id=engagement_participant_id,
            engagement_id=engagement_id,
            user_id=user_id,
            booked_by_user_id=booked_by,
        )
        session.add(participant)
        await session.flush()
    else:
        participant.booked_by_user_id = booked_by

    blood_row = (
        await session.execute(
            select(ParticipantBloodBooking).where(
                ParticipantBloodBooking.engagement_participant_id == engagement_participant_id
            )
        )
    ).scalars().first()
    if blood_row is None:
        blood_row = ParticipantBloodBooking(
            engagement_participant_id=engagement_participant_id,
            collection_date=collection_date,
            collection_time=collection_time,
            booking_id=booking_id,
            barcode=barcode,
        )
        session.add(blood_row)
    else:
        if collection_date is not None:
            blood_row.collection_date = collection_date
        if collection_time is not None:
            blood_row.collection_time = collection_time
        blood_row.booking_id = booking_id
        blood_row.barcode = barcode

    await session.flush()
    return participant


async def get_current_blood_booking(
    session: AsyncSession, *, engagement_participant_id: int
) -> ParticipantBloodBooking | None:
    return (
        await session.execute(
            select(ParticipantBloodBooking).where(
                ParticipantBloodBooking.engagement_participant_id == engagement_participant_id
            )
        )
    ).scalars().first()
