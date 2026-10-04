"""Shared Orange Health booking payload + slot normalization."""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from modules.diagnostics.models import DiagnosticPackage


def is_orange_health(pkg: DiagnosticPackage) -> bool:
    return (pkg.diagnostic_provider or "").strip().lower() == "orange_health"


def slim_orange_health_slots(slots_map: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Normalize OH serviceability slots dict to console/public slot list shape."""
    if not slots_map:
        return []
    out: list[dict[str, Any]] = []
    for key, slot in slots_map.items():
        if not isinstance(slot, dict):
            continue
        slot_dt = slot.get("slot_datetime") or key
        out.append(
            {
                "stm_id": str(slot_dt),
                "slot_datetime": str(slot_dt),
                "slot_date": str(slot_dt)[:10] if slot_dt else None,
                "slot_time": _format_slot_time_label(str(slot_dt)),
                "is_morning_slot": slot.get("is_morning_slot"),
                "is_afternoon_slot": slot.get("is_afternoon_slot"),
                "is_evening_slot": slot.get("is_evening_slot"),
            }
        )
    out.sort(key=lambda s: s.get("slot_datetime") or "")
    return out


def _format_slot_time_label(slot_datetime: str) -> str:
    try:
        dt = datetime.fromisoformat(slot_datetime.replace("Z", "+00:00"))
        return dt.strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return slot_datetime


def orange_health_gender(user_gender: str | None) -> str:
    g = (user_gender or "").strip().lower()
    if g in ("male", "m"):
        return "male"
    if g in ("female", "f"):
        return "female"
    return "other"


def build_orange_health_order_payload(
    *,
    participant_address: str,
    latitude: float | None,
    longitude: float | None,
    primary_name: str,
    primary_phone: str,
    slot_datetime: str | None,
    partner_notes: str,
    user_id: int,
    patient_name: str,
    patient_phone: str,
    age: int | str,
    gender: str,
    package_code: str,
) -> dict[str, Any]:
    location: dict[str, str] = {}
    if latitude is not None and longitude is not None:
        location = {
            "latitude": f"{round(float(latitude), 6):.6f}",
            "longitude": f"{round(float(longitude), 6):.6f}",
        }
    payload: dict[str, Any] = {
        "address": participant_address.strip(),
        "primary_patient_name": primary_name.strip(),
        "primary_patient_number": primary_phone.strip(),
        "payment_type": "paid_by_group",
        "partner_notes": partner_notes or "",
        "patient_details": [
            {
                "partner_reference_id": str(user_id),
                "patient_name": patient_name.strip(),
                "patient_phone": patient_phone.strip(),
                "age": str(age),
                "gender": orange_health_gender(gender),
                "packages": [{"package_id": package_code.strip()}],
            }
        ],
    }
    if location:
        payload["location"] = location
    if slot_datetime:
        payload["slot_datetime"] = slot_datetime
    return payload


def normalize_orange_provider_status(status: str | None) -> str | None:
    if not status:
        return None
    text = str(status).strip()
    if text.lower() == "scheduled":
        return "Scheduled"
    if text == "Scheduled":
        return "Scheduled"
    return None


def _pick_order_for_patient(orders: list[Any], user_id: int) -> dict[str, Any] | None:
    ref = str(user_id)
    for item in orders:
        if not isinstance(item, dict):
            continue
        partner_ref = item.get("partnerReferenceId") or item.get("partner_reference_id")
        if partner_ref is not None and str(partner_ref) == ref:
            return item
    if orders and isinstance(orders[0], dict):
        return orders[0]
    return None


def apply_orange_health_response_to_booking_row(
    coll_row: Any,
    oh_response: dict[str, Any],
    *,
    user_id: int | None = None,
) -> None:
    """Persist Orange Health create-order fields on participant_blood_bookings."""
    coll_row.diagnostic_provider = "orange_health"
    coll_row.request_id = oh_response.get("request_id")
    coll_row.token = oh_response.get("token")
    mapped_status = normalize_orange_provider_status(oh_response.get("status"))
    if mapped_status:
        coll_row.provider_status = mapped_status
    orders = oh_response.get("orders") or []
    first = _pick_order_for_patient(orders, user_id) if user_id is not None else (
        orders[0] if orders and isinstance(orders[0], dict) else None
    )
    if first:
        if first.get("id") is not None:
            coll_row.order_id = int(first["id"])
        alnum = first.get("alnumOrderId") or first.get("alnum_order_id")
        if alnum:
            coll_row.alnum_order_id = str(alnum)
    request_id = str(oh_response.get("request_id") or "")
    coll_row.booking_id = request_id
    alnum_order = (coll_row.alnum_order_id or "").strip()
    coll_row.barcode = alnum_order or request_id


def parse_orange_slot_time(slot_datetime: str) -> time:
    from datetime import time as time_type

    text = (slot_datetime or "").strip()
    if not text:
        raise ValueError("Empty slot datetime")
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return time_type(dt.hour, dt.minute, dt.second)
    except ValueError:
        return _parse_slot_time_fallback(text)


def _parse_slot_time_fallback(slot_datetime: str) -> time:
    from datetime import time as time_type

    if "T" in slot_datetime:
        part = slot_datetime.split("T", 1)[1]
        segments = part.split(":")
        if len(segments) >= 2:
            return time_type(int(segments[0]), int(segments[1]))
    raise ValueError(f"Invalid Orange Health slot datetime: {slot_datetime}")
