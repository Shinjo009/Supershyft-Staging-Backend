"""Shared Redcliffe home-collection booking helpers."""

from __future__ import annotations

import re
from datetime import date, time
from typing import Any

from modules.diagnostics.models import DiagnosticPackage


def is_redcliffe(pkg: DiagnosticPackage) -> bool:
    return (pkg.diagnostic_provider or "").strip().lower() == "redcliffe"


def is_redcliffe_provider(provider: str | None) -> bool:
    return (provider or "").strip().lower() == "redcliffe"


def build_redcliffe_place_query(
    *,
    address_line: str | None,
    landmark: str | None,
    city: str | None,
    pincode: str | None,
) -> str:
    """Build Redcliffe area-search query from booking address parts (full address preferred)."""
    parts = [
        (address_line or "").strip(),
        (landmark or "").strip(),
        (city or "").strip(),
        (pincode or "").strip(),
    ]
    return ", ".join(part for part in parts if part)


def redcliffe_gender(user_gender: str | None) -> str:
    g = (user_gender or "").strip().lower()
    if g in ("male", "m"):
        return "male"
    if g in ("female", "f"):
        return "female"
    raise ValueError("Gender must be male or female for Redcliffe booking")


def slim_redcliffe_slots(
    results: list[Any] | None,
    *,
    collection_date: date,
) -> list[dict[str, Any]]:
    if not results:
        return []
    out: list[dict[str, Any]] = []
    slot_date = collection_date.isoformat()
    for item in results:
        if not isinstance(item, dict):
            continue
        slot_id = item.get("id")
        if slot_id is None:
            continue
        fmt12 = item.get("format_12_hrs") if isinstance(item.get("format_12_hrs"), dict) else {}
        fmt24 = item.get("format_24_hrs") if isinstance(item.get("format_24_hrs"), dict) else {}
        start_12 = (fmt12.get("start_time") or "").strip()
        start_24 = (fmt24.get("start_time") or "").strip()
        slot_time = start_12 or start_24
        if not slot_time:
            continue
        out.append(
            {
                "stm_id": str(slot_id),
                "slot_date": slot_date,
                "slot_time": slot_time,
                "end_time": (fmt12.get("end_time") or fmt24.get("end_time") or "").strip() or None,
                "available_slot": item.get("available_slot"),
            }
        )
    out.sort(key=lambda s: (s.get("slot_time") or ""))
    return out


def parse_redcliffe_slot_time(slot_time_label: str) -> time:
    text = (slot_time_label or "").strip()
    if not text:
        raise ValueError("Empty slot time")
    meridiem_match = re.search(r"\b(AM|PM)\b", text, re.IGNORECASE)
    meridiem = meridiem_match.group(1).upper() if meridiem_match else None
    time_part = re.sub(r"\s*(AM|PM)\s*", "", text, flags=re.IGNORECASE).strip()
    segments = time_part.split(":")
    if len(segments) < 2:
        raise ValueError(f"Invalid slot time format: {slot_time_label}")
    hour = int(segments[0])
    minute = int(segments[1])
    if meridiem == "PM" and hour != 12:
        hour += 12
    elif meridiem == "AM" and hour == 12:
        hour = 0
    return time(hour, minute)


def build_redcliffe_create_payload(
    *,
    booking_date: date,
    collection_date: date,
    collection_slot: int,
    package_code: str,
    customer_name: str,
    customer_age: int,
    customer_gender: str,
    customer_email: str,
    customer_phone: str,
    customer_address: str,
    customer_landmark: str,
    pincode: str,
    latitude: float,
    longitude: float,
    reference_data: str,
    is_credit: bool = True,
    address_line2: str | None = None,
) -> dict[str, Any]:
    whatsapp = customer_phone.strip()
    payload: dict[str, Any] = {
        "booking_date": booking_date.isoformat(),
        "collection_date": collection_date.isoformat(),
        "collection_slot": int(collection_slot),
        "package_code": [package_code.strip()],
        "customer_name": customer_name.strip(),
        "customer_age": int(customer_age),
        "customer_gender": redcliffe_gender(customer_gender),
        "customer_email": customer_email.strip(),
        "customer_phonenumber": customer_phone.strip(),
        "customer_altphonenumber": customer_phone.strip(),
        "customer_whatsappnumber": whatsapp,
        "customer_address": customer_address.strip(),
        "customer_landmark": (customer_landmark or customer_address).strip(),
        "pincode": pincode.strip(),
        "customer_latitude": _coord(latitude),
        "customer_longitude": _coord(longitude),
        "is_credit": bool(is_credit),
        "reference_data": reference_data,
        "additional_member": [],
    }
    if address_line2 and address_line2.strip():
        payload["address_line2"] = address_line2.strip()
    return payload


def _coord(value: float) -> float:
    return round(float(value), 6)


def extract_redcliffe_booking_id(body: dict[str, Any]) -> str | None:
    for key in ("booking_id", "pk", "id"):
        val = body.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def apply_redcliffe_response_to_booking_row(
    coll_row: Any,
    *,
    create_response: dict[str, Any],
    confirm_response: dict[str, Any] | None = None,
) -> None:
    """Persist confirmed Redcliffe booking ids on participant_blood_bookings."""
    coll_row.diagnostic_provider = "redcliffe"
    booking_id = None
    if confirm_response:
        booking_id = extract_redcliffe_booking_id(confirm_response)
    if not booking_id:
        booking_id = extract_redcliffe_booking_id(create_response)
    if booking_id:
        coll_row.booking_id = booking_id
        coll_row.barcode = booking_id
    status = None
    if confirm_response and isinstance(confirm_response.get("booking_status"), str):
        status = confirm_response.get("booking_status")
    if status and str(status).strip().lower() == "confirmed":
        coll_row.provider_status = "Scheduled"