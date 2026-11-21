"""Redcliffe Labs paths for public / batch booking service."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from common.phone import to_healthians_mobile
from db.transaction import release_request_transaction
from modules.diagnostics.models import DiagnosticPackage
from modules.diagnostics.redcliffe import client as redcliffe_client
from modules.diagnostics.redcliffe.booking_helpers import (
    apply_redcliffe_response_to_booking_row,
    build_redcliffe_create_payload,
    extract_redcliffe_booking_id,
    parse_redcliffe_slot_time,
    redcliffe_gender,
    slim_redcliffe_slots,
)
from modules.diagnostics.redcliffe.client import (
    RedcliffeApiError,
    center_confirm_booking_api_url,
    center_create_booking_api_url,
    is_serviceable_response,
    serviceability_api_url,
    time_slot_list_api_url,
)
from modules.diagnostics.redcliffe.sync_log import log_redcliffe_call
from modules.engagements.blood_bookings_access import apply_schedule, get_current_row, get_or_create_current, read_schedule_from_row
from modules.engagements.models import Engagement, EngagementParticipant
from modules.engagements.participant_location import booking_location_field
from modules.metsights.service import outbound_last_name
from modules.users.models import User

logger = logging.getLogger(__name__)


async def check_serviceability_at_location(
    db: AsyncSession,
    *,
    latitude: float,
    longitude: float,
    engagement_id: int | None = None,
    engagement_code: str | None = None,
) -> dict[str, Any]:
    api_url = serviceability_api_url()
    req = {"latitude": latitude, "longitude": longitude}
    try:
        resp = await redcliffe_client.check_location_serviceable(latitude=latitude, longitude=longitude)
    except RedcliffeApiError as exc:
        await log_redcliffe_call(
            db,
            engagement_id=engagement_id,
            user_id=None,
            api_url=api_url,
            request_payload=req,
            response_payload=exc.body if isinstance(exc.body, dict) else None,
            status="failed",
            error_message=str(exc),
        )
        result: dict[str, Any] = {"status": "error", "message": str(exc)}
        if engagement_code:
            result["engagement_code"] = engagement_code
        return result
    except Exception as exc:
        await log_redcliffe_call(
            db,
            engagement_id=engagement_id,
            user_id=None,
            api_url=api_url,
            request_payload=req,
            status="failed",
            error_message=str(exc),
        )
        result = {"status": "error", "message": str(exc)}
        if engagement_code:
            result["engagement_code"] = engagement_code
        return result

    serviceable = is_serviceable_response(resp)
    await log_redcliffe_call(
        db,
        engagement_id=engagement_id,
        user_id=None,
        api_url=api_url,
        request_payload=req,
        response_payload=resp,
        status="success" if serviceable else "failed",
        error_message=None if serviceable else resp.get("message"),
    )
    if not serviceable:
        result = {
            "status": "error",
            "message": resp.get("message", "Location is non-serviceable"),
        }
        if engagement_code:
            result["engagement_code"] = engagement_code
        return result

    out = {
        "status": "success",
        "message": resp.get("message", "Location is serviceable"),
        "diagnostic_provider": "redcliffe",
    }
    if engagement_code:
        out["engagement_code"] = engagement_code
    return out


async def fetch_slots_for_location(
    db: AsyncSession,
    *,
    blood_collection_date: date,
    latitude: float,
    longitude: float,
    engagement_id: int | None = None,
    engagement_code: str | None = None,
    customer_gender: str | None = None,
) -> dict[str, Any]:
    collection_date = blood_collection_date.isoformat()
    api_url = time_slot_list_api_url()
    req: dict[str, Any] = {
        "collection_date": collection_date,
        "latitude": latitude,
        "longitude": longitude,
    }
    if customer_gender:
        req["customer_gender"] = customer_gender

    await release_request_transaction(db)
    try:
        resp = await redcliffe_client.get_time_slot_list(
            collection_date=collection_date,
            latitude=latitude,
            longitude=longitude,
            customer_gender=customer_gender,
        )
    except RedcliffeApiError as exc:
        await log_redcliffe_call(
            db,
            engagement_id=engagement_id,
            user_id=None,
            api_url=api_url,
            request_payload=req,
            response_payload=exc.body if isinstance(exc.body, dict) else None,
            status="failed",
            error_message=str(exc),
        )
        result = {"status": "error", "message": str(exc)}
        if engagement_code:
            result["engagement_code"] = engagement_code
        return result
    except Exception as exc:
        await log_redcliffe_call(
            db,
            engagement_id=engagement_id,
            user_id=None,
            api_url=api_url,
            request_payload=req,
            status="failed",
            error_message=str(exc),
        )
        result = {"status": "error", "message": str(exc)}
        if engagement_code:
            result["engagement_code"] = engagement_code
        return result

    await log_redcliffe_call(
        db,
        engagement_id=engagement_id,
        user_id=None,
        api_url=api_url,
        request_payload=req,
        response_payload=resp,
        status="success",
    )
    raw = resp.get("results")
    if raw is None:
        raw = resp.get("data")
    slots_list = raw if isinstance(raw, list) else []
    slim = slim_redcliffe_slots(slots_list, collection_date=blood_collection_date)
    out: dict[str, Any] = {
        "status": "success",
        "slots": slim,
        "diagnostic_provider": "redcliffe",
        "message": resp.get("message"),
    }
    if engagement_code:
        out["engagement_code"] = engagement_code
    return out


async def lock_slot_local(
    db: AsyncSession,
    *,
    participant: EngagementParticipant,
    blood_collection_date: date,
    slot_id: str,
    slot_time_label: str,
) -> None:
    try:
        collection_slot = int(slot_id.strip())
    except ValueError as exc:
        raise ValueError(f"Invalid Redcliffe slot id: {slot_id}") from exc
    slot_start = parse_redcliffe_slot_time(slot_time_label)
    await apply_schedule(
        db,
        participant,
        engagement_date=blood_collection_date,
        slot_start_time=slot_start,
        blood_collection_time_slot_id=str(collection_slot),
    )


async def create_booking_for_member(
    db: AsyncSession,
    *,
    engagement_id: int,
    user_id: int,
    participant: EngagementParticipant,
    engagement: Engagement,
    user: User,
    pkg: DiagnosticPackage,
    partner_notes: str = "",
    is_credit: bool = True,
) -> dict[str, Any]:
    _ = partner_notes
    coll_row = await get_current_row(db, participant)
    sched = read_schedule_from_row(coll_row)
    slot_raw = (sched["blood_collection_time_slot_id"] or "").strip()
    package_code = (pkg.external_package_code or "").strip()
    if not package_code or not slot_raw:
        return {"user_id": user_id, "engagement_id": engagement_id, "status": "error", "message": "Missing slot or package code"}

    try:
        collection_slot = int(slot_raw)
    except ValueError:
        return {"user_id": user_id, "engagement_id": engagement_id, "status": "error", "message": "Invalid slot id"}

    collection_date = sched["engagement_date"]
    if collection_date is None:
        return {"user_id": user_id, "engagement_id": engagement_id, "status": "error", "message": "Collection date is not set"}

    first_name = (user.first_name or "").strip()
    last_name = outbound_last_name(user.last_name)
    phone = to_healthians_mobile((user.phone or "").strip())
    email = (user.email or "").strip()
    if not first_name or len(phone) != 10 or user.age is None or not email or "@" not in email:
        return {
            "user_id": user_id,
            "engagement_id": engagement_id,
            "status": "error",
            "message": "Incomplete participant profile (name, phone, age, email)",
        }
    try:
        redcliffe_gender(user.gender)
    except ValueError:
        return {
            "user_id": user_id,
            "engagement_id": engagement_id,
            "status": "error",
            "message": "Participant gender must be male or female for Redcliffe",
        }

    address_raw = booking_location_field(participant, engagement, "address")
    address = (str(address_raw).strip() if address_raw is not None else "")
    landmark_raw = booking_location_field(participant, engagement, "landmark")
    landmark = (str(landmark_raw).strip() if landmark_raw is not None else "")
    pincode_raw = booking_location_field(participant, engagement, "pincode")
    pincode = (str(pincode_raw).strip() if pincode_raw is not None else "")
    lat = booking_location_field(participant, engagement, "latitude")
    lng = booking_location_field(participant, engagement, "longitude")
    if not address or not pincode or lat is None or lng is None:
        return {"user_id": user_id, "engagement_id": engagement_id, "status": "error", "message": "Missing address or location"}

    patient_name = f"{first_name} {last_name}".strip()
    create_payload = build_redcliffe_create_payload(
        booking_date=date.today(),
        collection_date=collection_date,
        collection_slot=collection_slot,
        package_code=package_code,
        customer_name=patient_name,
        customer_age=int(user.age),
        customer_gender=user.gender or "",
        customer_email=email,
        customer_phone=phone,
        customer_address=address,
        customer_landmark=landmark or address,
        pincode=pincode,
        latitude=float(lat),
        longitude=float(lng),
        reference_data=f"{engagement_id}:{user_id}",
        is_credit=is_credit,
    )

    create_url = center_create_booking_api_url()
    await release_request_transaction(db)
    try:
        create_resp = await redcliffe_client.center_create_booking(create_payload)
    except Exception as exc:
        await log_redcliffe_call(
            db,
            engagement_id=engagement_id,
            user_id=user_id,
            api_url=create_url,
            request_payload=create_payload,
            status="failed",
            error_message=str(exc),
        )
        return {"user_id": user_id, "engagement_id": engagement_id, "status": "error", "message": str(exc)}

    await log_redcliffe_call(
        db,
        engagement_id=engagement_id,
        user_id=user_id,
        api_url=create_url,
        request_payload=create_payload,
        response_payload=create_resp,
        status="success",
    )

    temp_booking_id = extract_redcliffe_booking_id(create_resp)
    if not temp_booking_id:
        return {
            "user_id": user_id,
            "engagement_id": engagement_id,
            "status": "error",
            "message": "Redcliffe did not return a booking id",
        }

    confirm_url = center_confirm_booking_api_url()
    confirm_payload = {"booking_id": temp_booking_id, "is_confirmed": True}
    try:
        confirm_resp = await redcliffe_client.center_confirm_booking(
            booking_id=temp_booking_id,
            is_confirmed=True,
        )
    except Exception as exc:
        await log_redcliffe_call(
            db,
            engagement_id=engagement_id,
            user_id=user_id,
            api_url=confirm_url,
            request_payload=confirm_payload,
            status="failed",
            error_message=str(exc),
        )
        return {"user_id": user_id, "engagement_id": engagement_id, "status": "error", "message": str(exc)}

    await log_redcliffe_call(
        db,
        engagement_id=engagement_id,
        user_id=user_id,
        api_url=confirm_url,
        request_payload=confirm_payload,
        response_payload=confirm_resp,
        status="success",
    )

    coll_row = await get_or_create_current(db, participant)
    apply_redcliffe_response_to_booking_row(
        coll_row,
        create_response=create_resp,
        confirm_response=confirm_resp,
    )
    db.add(coll_row)
    await db.flush()

    final_id = extract_redcliffe_booking_id(confirm_resp) or temp_booking_id
    return {
        "user_id": user_id,
        "engagement_id": engagement_id,
        "status": "success",
        "message": confirm_resp.get("message", "Booking placed"),
        "booking_id": final_id,
        "diagnostic_provider": "redcliffe",
    }