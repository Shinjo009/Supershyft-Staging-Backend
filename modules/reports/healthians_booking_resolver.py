"""Resolve Healthians booking id from participant or Metsights fetch-collections."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppError
from db.transaction import release_request_transaction
from modules.diagnostics.models import DiagnosticPackage
from modules.engagements.blood_bookings_repository import BloodBookingsRepository
from modules.engagements.diagnostic_package_resolution import resolve_diagnostic_package_id
from modules.engagements.models import Engagement, EngagementParticipant
from modules.metsights.service import MetsightsService
from modules.users.models import User
from modules.reports.blood_parameters_schemas import (
    booking_id_from_fetch_collections,
    provider_code_from_field,
)

# Skip re-calling Healthians for booking IDs that recently returned Invalid Booking ID.
_invalid_booking_ids: dict[str, float] = {}
_INVALID_BOOKING_TTL_SECONDS = 30 * 60


def remember_invalid_healthians_booking_id(booking_id: str) -> None:
    bid = (booking_id or "").strip()
    if bid:
        _invalid_booking_ids[bid] = time.monotonic()


def is_known_invalid_healthians_booking_id(booking_id: str) -> bool:
    bid = (booking_id or "").strip()
    if not bid:
        return False
    seen_at = _invalid_booking_ids.get(bid)
    if seen_at is None:
        return False
    if (time.monotonic() - seen_at) > _INVALID_BOOKING_TTL_SECONDS:
        _invalid_booking_ids.pop(bid, None)
        return False
    return True


class HealthiansBookingSource(str, Enum):
    PARTICIPANT = "participant"
    METSIGHTS = "metsights"


@dataclass(frozen=True)
class ResolvedHealthiansBooking:
    booking_id: str
    source: HealthiansBookingSource
    collection_data: dict[str, Any] | None = None


def is_healthians_diagnostic_provider(diagnostic_provider: str | None) -> bool:
    return (diagnostic_provider or "").strip().lower() == "healthians"


async def _provider_for_engagement_packages(
    db: AsyncSession,
    *,
    unisex_provider: str | None,
    male_package_id: int | None,
    female_package_id: int | None,
    user_id: int,
) -> str | None:
    """Provider for the booked package. Either gender package counts when gender is unknown."""
    if male_package_id is None and female_package_id is None:
        return unisex_provider

    class _EngagementPackages:
        diagnostic_package_id = None
        diagnostic_package_id_male = male_package_id
        diagnostic_package_id_female = female_package_id

    user = await db.get(User, user_id)
    try:
        package_id = resolve_diagnostic_package_id(
            _EngagementPackages(),
            user_gender=user.gender if user is not None else None,
        )
    except AppError:
        package_id = None
    if package_id is not None:
        package = await db.get(DiagnosticPackage, package_id)
        return package.diagnostic_provider if package is not None else None

    gender_ids = [package_id for package_id in (male_package_id, female_package_id) if package_id is not None]
    if not gender_ids:
        return None
    providers = (
        await db.execute(
            select(DiagnosticPackage.diagnostic_provider).where(
                DiagnosticPackage.diagnostic_package_id.in_(gender_ids)
            )
        )
    ).scalars().all()
    if any(is_healthians_diagnostic_provider(provider) for provider in providers):
        return "healthians"
    return providers[0] if providers else None


def try_participant_booking_id(
    participant_booking_id: str | None,
    diagnostic_provider: str | None,
) -> str | None:
    """Return participant booking_id when the engagement package is Healthians."""
    booking_id = (participant_booking_id or "").strip()
    if not booking_id:
        return None
    provider = (diagnostic_provider or "").strip()
    if provider and not is_healthians_diagnostic_provider(provider):
        return None
    return booking_id


async def _load_participant_booking_context(
    db: AsyncSession,
    *,
    user_id: int,
    engagement_id: int,
) -> tuple[str | None, str | None]:
    result = await db.execute(
        select(
            EngagementParticipant.engagement_participant_id,
            DiagnosticPackage.diagnostic_provider,
            Engagement.diagnostic_package_id_male,
            Engagement.diagnostic_package_id_female,
        )
        .join(Engagement, Engagement.engagement_id == EngagementParticipant.engagement_id)
        .outerjoin(
            DiagnosticPackage,
            DiagnosticPackage.diagnostic_package_id == Engagement.diagnostic_package_id,
        )
        .where(EngagementParticipant.user_id == user_id)
        .where(EngagementParticipant.engagement_id == engagement_id)
        .order_by(EngagementParticipant.engagement_participant_id.desc())
        .limit(1)
    )
    row = result.one_or_none()
    if row is None:
        return None, None
    ep_id, provider, male_package_id, female_package_id = row
    blood_repo = BloodBookingsRepository()
    current = await blood_repo.get_current_collection(db, engagement_participant_id=int(ep_id))
    booking_id = (current.booking_id if current else None) or None
    resolved_provider = await _provider_for_engagement_packages(
        db,
        unisex_provider=provider,
        male_package_id=male_package_id,
        female_package_id=female_package_id,
        user_id=user_id,
    )
    return booking_id, resolved_provider


async def resolve_healthians_booking_id(
    db: AsyncSession,
    *,
    user_id: int,
    engagement_id: int,
    record_id: str,
    metsights_service: MetsightsService,
    participant_booking_id: str | None = None,
    diagnostic_provider: str | None = None,
) -> ResolvedHealthiansBooking:
    """Prefer engagement_participants.booking_id for Healthians; else Metsights fetch-collections."""
    rid = (record_id or "").strip()
    if not rid:
        raise AppError(
            status_code=422,
            error_code="INVALID_STATE",
            message="Metsights record id is missing",
        )

    if participant_booking_id is None and diagnostic_provider is None:
        participant_booking_id, diagnostic_provider = await _load_participant_booking_context(
            db,
            user_id=user_id,
            engagement_id=engagement_id,
        )

    from_participant = try_participant_booking_id(participant_booking_id, diagnostic_provider)
    if from_participant:
        return ResolvedHealthiansBooking(
            booking_id=from_participant,
            source=HealthiansBookingSource.PARTICIPANT,
        )

    await release_request_transaction(db)

    collection_data = await metsights_service.get_fetch_collections(record_id=rid)
    provider_code = provider_code_from_field(collection_data.get("provider"))
    if provider_code.lower() != "healthians":
        raise AppError(
            status_code=422,
            error_code="INVALID_STATE",
            message=(
                f"Blood report provider is '{provider_code or 'unknown'}', "
                "only Healthians is supported for provider load"
            ),
        )

    reference_id = booking_id_from_fetch_collections(collection_data)
    if not reference_id:
        raise AppError(
            status_code=422,
            error_code="INVALID_STATE",
            message="Metsights collection is missing the provider booking id",
        )

    return ResolvedHealthiansBooking(
        booking_id=reference_id,
        source=HealthiansBookingSource.METSIGHTS,
        collection_data=collection_data,
    )
