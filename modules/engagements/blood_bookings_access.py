"""Helpers to read/write collection fields via participant_blood_bookings."""

from __future__ import annotations

from datetime import date, time

from sqlalchemy.ext.asyncio import AsyncSession

from modules.engagements.blood_bookings_repository import BloodBookingsRepository
from modules.engagements.models import EngagementParticipant, ParticipantBloodBooking

_repo = BloodBookingsRepository()


async def get_current_row(
    db: AsyncSession,
    participant: EngagementParticipant,
) -> ParticipantBloodBooking | None:
    return await _repo.get_current_collection(
        db,
        engagement_participant_id=participant.engagement_participant_id,
    )


async def get_or_create_current(
    db: AsyncSession,
    participant: EngagementParticipant,
) -> ParticipantBloodBooking:
    return await _repo.get_or_create_current_collection(
        db,
        engagement_participant_id=participant.engagement_participant_id,
    )


async def current_booking_id(db: AsyncSession, participant: EngagementParticipant) -> str | None:
    row = await get_current_row(db, participant)
    if row is None:
        return None
    bid = (row.booking_id or "").strip()
    return bid or None


async def has_active_booking(db: AsyncSession, participant: EngagementParticipant) -> bool:
    return await _repo.has_active_booking_id(
        db,
        engagement_participant_id=participant.engagement_participant_id,
    )


async def apply_schedule(
    db: AsyncSession,
    participant: EngagementParticipant,
    *,
    engagement_date: date | None = None,
    slot_start_time: time | None = None,
    blood_collection_cabin: str | None = None,
    blood_collection_time_slot_id: str | None = None,
) -> ParticipantBloodBooking:
    row = await get_or_create_current(db, participant)
    if engagement_date is not None:
        row.collection_date = engagement_date
    if slot_start_time is not None:
        row.collection_time = slot_start_time
    if blood_collection_cabin is not None:
        row.collection_cabin = blood_collection_cabin
    if blood_collection_time_slot_id is not None:
        row.collection_time_slot_id = blood_collection_time_slot_id
    db.add(row)
    await db.flush()
    return row


def read_schedule_from_row(row: ParticipantBloodBooking | None) -> dict:
    if row is None:
        return {
            "engagement_date": None,
            "slot_start_time": None,
            "blood_collection_cabin": None,
            "blood_collection_time_slot_id": None,
            "barcode": None,
            "booking_id": None,
        }
    return {
        "engagement_date": row.collection_date,
        "slot_start_time": row.collection_time,
        "blood_collection_cabin": row.collection_cabin,
        "blood_collection_time_slot_id": row.collection_time_slot_id,
        "barcode": row.barcode,
        "booking_id": row.booking_id,
    }
