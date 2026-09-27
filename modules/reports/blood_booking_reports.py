"""Read/write blood lab data on participant_blood_bookings."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.engagements.blood_booking_enums import BloodBookingStatus
from modules.engagements.blood_bookings_repository import BloodBookingsRepository
from modules.engagements.models import EngagementParticipant, ParticipantBloodBooking
from modules.reports.blood_parameters_schemas import has_usable_provider_blood_parameters
from modules.reports.blood_report_archival import is_archived_blood_report_url


async def get_participant_for_user_engagement(
    db: AsyncSession,
    *,
    user_id: int,
    engagement_id: int,
) -> EngagementParticipant | None:
    result = await db.execute(
        select(EngagementParticipant)
        .where(EngagementParticipant.user_id == user_id)
        .where(EngagementParticipant.engagement_id == engagement_id)
        .order_by(EngagementParticipant.engagement_participant_id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_current_report_root(
    db: AsyncSession,
    *,
    user_id: int,
    engagement_id: int,
) -> ParticipantBloodBooking | None:
    participant = await get_participant_for_user_engagement(
        db, user_id=user_id, engagement_id=engagement_id
    )
    if participant is None:
        return None
    repo = BloodBookingsRepository()
    current = await repo.get_current_collection(
        db, engagement_participant_id=participant.engagement_participant_id
    )
    if current is None:
        return None
    return await repo.get_report_root(db, collection_row=current)


def merged_blood_parameters_blob(root: ParticipantBloodBooking | None) -> Any | None:
    """Return stored blood_parameters for the current report group (root row)."""
    if root is None:
        return None
    if has_usable_provider_blood_parameters(root.blood_parameters):
        return root.blood_parameters
    return None


async def list_archived_diagnostic_urls(
    db: AsyncSession,
    *,
    engagement_participant_id: int,
) -> list[str]:
    repo = BloodBookingsRepository()
    groups = await repo.list_active_report_groups(
        db, engagement_participant_id=engagement_participant_id
    )
    urls: list[str] = []
    seen: set[str] = set()
    for group in groups:
        root = await repo.get_report_root(db, collection_row=group)
        url = (root.diagnostic_report_url or "").strip()
        if not url or not is_archived_blood_report_url(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


async def clear_blood_report_data_for_participant(
    db: AsyncSession,
    *,
    engagement_participant_id: int,
) -> None:
    result = await db.execute(
        select(ParticipantBloodBooking).where(
            ParticipantBloodBooking.engagement_participant_id == engagement_participant_id
        )
    )
    for row in result.scalars().all():
        row.blood_parameters = None
        row.blood_report_raw = None
        row.diagnostic_report_url = None
        row.blood_parameters_full_report = None
        row.blood_parameters_verified_at = None
        db.add(row)
    await db.flush()
