"""Validate Healthians booking_id assignment on active blood collection rows."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppError
from modules.engagements.blood_bookings_repository import BloodBookingsRepository
from modules.engagements.models import EngagementParticipant
from modules.users.models import User

_repo = BloodBookingsRepository()


async def _participant_label(db: AsyncSession, *, engagement_participant_id: int) -> str:
    result = await db.execute(
        select(User.first_name, User.last_name, User.user_id)
        .select_from(EngagementParticipant)
        .join(User, User.user_id == EngagementParticipant.user_id)
        .where(EngagementParticipant.engagement_participant_id == engagement_participant_id)
    )
    row = result.one_or_none()
    if row is None:
        return f"participant #{engagement_participant_id}"
    first, last, user_id = row
    name = f"{first or ''} {last or ''}".strip()
    if name:
        return f"{name} (user {user_id})"
    return f"user {user_id}"


async def ensure_active_booking_id_available(
    db: AsyncSession,
    *,
    booking_id: str | None,
    exclude_pbb_id: int | None = None,
) -> None:
    """Raise when another active collection already uses this booking ID."""
    bid = (booking_id or "").strip()
    if not bid:
        return

    existing = await _repo.get_active_by_booking_id(db, booking_id=bid)
    if existing is None:
        return
    if exclude_pbb_id is not None and int(existing.id) == int(exclude_pbb_id):
        return

    label = await _participant_label(db, engagement_participant_id=int(existing.engagement_participant_id))
    raise AppError(
        status_code=409,
        error_code="BOOKING_ID_EXISTS",
        message=f"This booking ID is already on an active collection ({label}).",
    )


def booking_id_integrity_app_error(exc: Exception) -> AppError | None:
    """Map unique-index violations on booking_id to a client-safe 409."""
    orig = getattr(exc, "orig", None)
    text = str(orig or exc)
    if "uq_pbb_booking_id" in text or (
        "participant_blood_bookings" in text and "booking_id" in text.lower()
    ):
        return AppError(
            status_code=409,
            error_code="BOOKING_ID_EXISTS",
            message="This booking ID is already on an active collection.",
        )
    return None
