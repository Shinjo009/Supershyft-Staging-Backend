"""Parse Orange Health webhook bodies and resolve local identity for sync logs."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppError
from modules.engagements.blood_bookings_repository import BloodBookingsRepository
from modules.engagements.models import EngagementParticipant
from modules.users.models import User


def parse_orange_health_webhook_body(raw_body: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppError(
            status_code=400,
            error_code="INVALID_PAYLOAD",
            message="Invalid JSON webhook body",
        ) from exc
    if not isinstance(parsed, dict):
        raise AppError(
            status_code=400,
            error_code="INVALID_PAYLOAD",
            message="Webhook body must be a JSON object",
        )
    return parsed


def build_sync_log_request_payload(
    *,
    body: dict[str, Any],
    x_oh_event_id: str | None,
) -> dict[str, Any]:
    event = str(body.get("event") or "").strip()
    payload: dict[str, Any] = {
        "event": event or None,
        "x_oh_event_id": (x_oh_event_id or "").strip() or None,
        "body": body,
    }
    return payload


def _dig_str(data: Any, *keys: str) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def extract_booking_lookup_keys(body: dict[str, Any]) -> list[str]:
    """Collect candidate booking_id / request_id values for PBB lookup."""
    keys: list[str] = []
    seen: set[str] = set()

    def add(raw: str | None) -> None:
        text = (raw or "").strip()
        if text and text not in seen:
            seen.add(text)
            keys.append(text)

    payload = body.get("payload")
    if isinstance(payload, dict):
        order = payload.get("order")
        if isinstance(order, dict):
            add(_dig_str(order, "city_request_id"))
            add(_dig_str(order, "request_id"))
            add(_dig_str(order, "alnum_order_id"))
            oid = order.get("id")
            if oid is not None:
                add(str(oid))
        request = payload.get("request")
        if isinstance(request, dict):
            add(_dig_str(request, "id", "request_id", "city_request_id"))
        elif request is not None:
            add(str(request))

    add(_dig_str(body, "request_id"))

    return keys


def extract_partner_reference_id(body: dict[str, Any]) -> int | None:
    payload = body.get("payload")
    if not isinstance(payload, dict):
        return None

    order = payload.get("order")
    if isinstance(order, dict):
        ref = _dig_str(order, "partner_reference_id", "partnerReferenceId")
        if ref:
            try:
                return int(ref)
            except ValueError:
                return None

    for key in ("customer_details", "patient_details"):
        block = payload.get(key)
        if isinstance(block, dict):
            ref = _dig_str(block, "partner_reference_id", "partnerReferenceId")
            if ref:
                try:
                    return int(ref)
                except ValueError:
                    return None
        if isinstance(block, list):
            for item in block:
                if isinstance(item, dict):
                    ref = _dig_str(item, "partner_reference_id", "partnerReferenceId")
                    if ref:
                        try:
                            return int(ref)
                        except ValueError:
                            continue
    return None


async def resolve_webhook_engagement_context(
    db: AsyncSession,
    body: dict[str, Any],
) -> tuple[int | None, int | None]:
    """Best-effort engagement_id and user_id from PBB or partner_reference_id."""
    blood_repo = BloodBookingsRepository()
    engagement_id: int | None = None
    user_id: int | None = None

    for booking_key in extract_booking_lookup_keys(body):
        row = await blood_repo.get_by_booking_id(db, booking_id=booking_key)
        if row is None and booking_key.isdigit():
            row = await blood_repo.get_by_booking_id(db, booking_id=booking_key)
        if row is None:
            continue
        result = await db.execute(
            select(EngagementParticipant).where(
                EngagementParticipant.engagement_participant_id == row.engagement_participant_id
            )
        )
        participant = result.scalar_one_or_none()
        if participant is not None:
            engagement_id = int(participant.engagement_id)
            user_id = int(participant.user_id)
            return engagement_id, user_id

    ref_user = extract_partner_reference_id(body)
    if ref_user is not None:
        exists = await db.execute(select(User.user_id).where(User.user_id == ref_user).limit(1))
        if exists.scalar_one_or_none() is not None:
            user_id = ref_user

    return engagement_id, user_id
