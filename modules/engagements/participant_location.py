"""Copy home-collection location onto engagement_participants."""

from __future__ import annotations

from typing import Any, Protocol

from modules.engagements.models import Engagement, EngagementParticipant


class _OnboardAddressPayload(Protocol):
    address: str | None
    pincode: str | None
    city: str | None
    state: str | None
    country: str | None


def participant_has_home_location(participant: EngagementParticipant) -> bool:
    address = (participant.address or "").strip()
    pincode = (participant.pincode or "").strip()
    return bool(address or pincode)


def copy_engagement_location_to_participant(
    participant: EngagementParticipant,
    engagement: Engagement,
) -> None:
    """Mirror geocoded B2C engagement location onto the participant row."""
    participant.address = engagement.address
    participant.sub_locality = engagement.sub_locality
    participant.landmark = engagement.landmark
    participant.pincode = engagement.pincode
    participant.city = engagement.city
    participant.state = engagement.state
    participant.country = engagement.country
    participant.latitude = engagement.latitude
    participant.longitude = engagement.longitude
    participant.healthians_zone_id = engagement.healthians_zone_id


def copy_onboard_payload_location_to_participant(
    participant: EngagementParticipant,
    payload: _OnboardAddressPayload,
) -> None:
    """Set participant home address from onboard payload (no lat/long until booking geocodes)."""
    if payload.address is not None:
        stripped = payload.address.strip()
        participant.address = stripped or None
        participant.sub_locality = stripped or None
    if payload.pincode is not None:
        participant.pincode = payload.pincode.strip() or None
    if payload.city is not None:
        participant.city = payload.city.strip() or None
    if payload.state is not None:
        participant.state = payload.state.strip() or None
    if payload.country is not None:
        participant.country = payload.country.strip() or None


def onboard_payload_has_address(payload: _OnboardAddressPayload) -> bool:
    for value in (
        payload.address,
        payload.pincode,
        payload.city,
        payload.state,
        payload.country,
    ):
        if value is not None and str(value).strip():
            return True
    return False


def address_profile_update_from_onboard_payload(payload: _OnboardAddressPayload) -> dict[str, Any]:
    """Map onboard payload location fields to users table column names."""
    update: dict[str, Any] = {}
    if payload.address is not None:
        update["address"] = payload.address
    if payload.pincode is not None:
        update["pin_code"] = payload.pincode
    if payload.city is not None:
        update["city"] = payload.city
    if payload.state is not None:
        update["state"] = payload.state
    if payload.country is not None:
        update["country"] = payload.country
    return update


def use_participant_home_for_booking(
    engagement: Engagement,
    participant: EngagementParticipant,
) -> bool:
    """Shared (B2B) engagements use participant home address when present."""
    if engagement.organization_id is None:
        return False
    return participant_has_home_location(participant)


def booking_location_field(
    participant: EngagementParticipant,
    engagement: Engagement,
    field: str,
) -> Any:
    """Resolve a home-collection field for partner booking and slot APIs."""
    if engagement.organization_id is None:
        return getattr(engagement, field, None)
    if participant_has_home_location(participant):
        return getattr(participant, field, None)
    return getattr(engagement, field, None)


def overlay_console_display_address(
    payload: dict[str, Any],
    *,
    participant: EngagementParticipant | None,
    engagement: Engagement,
) -> None:
    """Prefill console home-collection forms: participant, then engagement, then user row."""
    if participant is not None and participant_has_home_location(participant):
        payload["address"] = participant.address
        payload["pin_code"] = participant.pincode
        payload["city"] = participant.city
        payload["state"] = participant.state
        payload["landmark"] = participant.landmark
        return

    engagement_address = (engagement.address or "").strip()
    engagement_pincode = (engagement.pincode or "").strip()
    if engagement_address or engagement_pincode:
        payload["address"] = engagement.address
        payload["pin_code"] = engagement.pincode
        payload["city"] = engagement.city
        payload["state"] = engagement.state
        payload["landmark"] = engagement.landmark
        return

    payload.setdefault("landmark", None)
