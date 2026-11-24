"""Orange Health reschedule partner body, slot revalidation, and sync-log helpers."""

from __future__ import annotations

from datetime import date
from typing import Any

from core.exceptions import AppError
from modules.diagnostics.orange_health import client as orange_health_client
from modules.diagnostics.orange_health.booking_helpers import slim_orange_health_slots
from modules.diagnostics.orange_health.client import OrangeHealthApiError
from modules.engagements.models import EngagementParticipant

ORANGE_RESCHEDULE_PARTNER_KEYS = frozenset(
    {"requested_slot_time", "reschedule_reason", "reschedule_explanation"}
)


def build_orange_reschedule_partner_body(
    *,
    requested_slot_time: str,
    reschedule_reason: str,
    reschedule_explanation: str,
) -> dict[str, str]:
    slot = (requested_slot_time or "").strip()
    reason = (reschedule_reason or "").strip()
    explanation = (reschedule_explanation or "").strip()
    if not slot:
        raise AppError(
            status_code=422,
            error_code="INVALID_SLOT_TIME",
            message="Requested slot time is required",
        )
    if not reason:
        raise AppError(
            status_code=422,
            error_code="INVALID_RESCHEDULE_REASON",
            message="Reschedule reason is required",
        )
    if not explanation:
        raise AppError(
            status_code=422,
            error_code="INVALID_RESCHEDULE_EXPLANATION",
            message="Reschedule explanation is required",
        )
    return {
        "requested_slot_time": slot,
        "reschedule_reason": reason,
        "reschedule_explanation": explanation,
    }


def sanitize_orange_reschedule_patch_body(payload: dict[str, Any]) -> dict[str, str]:
    """Keep only Orange Partner reschedule JSON body fields."""
    return build_orange_reschedule_partner_body(
        requested_slot_time=str(payload.get("requested_slot_time", "")),
        reschedule_reason=str(payload.get("reschedule_reason", "")),
        reschedule_explanation=str(payload.get("reschedule_explanation", "")),
    )


def _slot_id_matches_partner(partner_slot: str, requested: str) -> bool:
    a = (partner_slot or "").strip()
    b = (requested or "").strip()
    if not a or not b:
        return False
    if a == b:
        return True
    return a.replace(" ", "") == b.replace(" ", "")


def _find_matched_slot(slots_map: dict[str, Any] | None, locked_slot_id: str) -> dict[str, Any] | None:
    for slim in slim_orange_health_slots(slots_map):
        stm = str(slim.get("stm_id") or slim.get("slot_datetime") or "")
        if _slot_id_matches_partner(stm, locked_slot_id):
            return slim
    if slots_map:
        for key, slot in slots_map.items():
            if not isinstance(slot, dict):
                continue
            slot_dt = str(slot.get("slot_datetime") or key)
            if _slot_id_matches_partner(slot_dt, locked_slot_id):
                return {
                    "stm_id": slot_dt,
                    "slot_datetime": slot_dt,
                    **slot,
                }
    return None


async def revalidate_orange_reschedule_slot(
    *,
    participant: EngagementParticipant,
    blood_collection_date: date,
    locked_slot_id: str,
    blood_collection_time_slot: str,
) -> tuple[str, dict[str, Any]]:
    """
  Reload serviceability and confirm locked slot is still offered.
    Returns canonical partner requested_slot_time and internal revalidation metadata.
    """
    lat = participant.latitude
    lng = participant.longitude
    if lat is None or lng is None:
        raise AppError(
            status_code=422,
            error_code="MISSING_LOCATION",
            message="Participant location is required to validate Orange Health slots",
        )
    request_date = blood_collection_date.isoformat()
    locked = (locked_slot_id or "").strip()
    if not locked:
        raise AppError(
            status_code=422,
            error_code="SLOT_NOT_LOCKED",
            message="Blood collection slot has not been locked",
        )
    try:
        resp = await orange_health_client.check_serviceability(
            latitude=float(lat),
            longitude=float(lng),
            request_date=request_date,
        )
    except OrangeHealthApiError as exc:
        raise AppError(
            status_code=422 if exc.status_code == 400 else 502,
            error_code="ORANGE_HEALTH_SERVICEABILITY_FAILED",
            message=str(exc),
        ) from exc

    slots_map = resp.get("slots") if isinstance(resp.get("slots"), dict) else {}
    matched = _find_matched_slot(slots_map, locked)
    revalidation: dict[str, Any] = {
        "status": "matched" if matched else "not_found",
        "request_date": request_date,
        "partner_slot_key": locked,
        "raw_slot_id_from_client": locked,
        "requested_slot_time_display_ist": locked,
    }
    if not matched:
        raise AppError(
            status_code=422,
            error_code="SLOT_NOT_AVAILABLE",
            message="Requested slot is no longer available from Orange Health. Please select a new slot.",
        )

    partner_slot = str(matched.get("slot_datetime") or matched.get("stm_id") or locked)
    revalidation["matched_slot"] = {
        k: matched.get(k)
        for k in (
            "slot_datetime",
            "is_morning_slot",
            "is_afternoon_slot",
            "is_evening_slot",
            "slot_time",
        )
        if matched.get(k) is not None
    }
    revalidation["partner_slot_raw"] = partner_slot

    internal_slot = {
        "blood_collection_date": request_date,
        "locked_slot_id_on_row": locked,
        "raw_slot_id_from_client": locked,
        "requested_slot_time_display_ist": partner_slot,
        "blood_collection_time_slot_label": (blood_collection_time_slot or "").strip() or None,
    }
    return partner_slot, {"revalidation": revalidation, "slot": internal_slot}


def token_suffix(token: str | None) -> str | None:
    text = (token or "").strip()
    if len(text) < 8:
        return None
    return text[-8:]


def build_reschedule_internal_metadata(
    *,
    request_id: str,
    token: str | None,
    slot_meta: dict[str, Any],
    blood_collection_date: date,
) -> dict[str, Any]:
    return {
        "operation": "reschedule",
        "request_id": request_id,
        "token_suffix": token_suffix(token),
        "blood_collection_date": blood_collection_date.isoformat(),
        **slot_meta,
    }