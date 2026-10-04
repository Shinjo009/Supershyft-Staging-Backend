"""Orange Health paths for public / batch booking service."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppError
from db.transaction import release_request_transaction
from modules.diagnostics.models import DiagnosticPackage
from modules.diagnostics.orange_health import client as orange_health_client
from modules.diagnostics.orange_health.client import order_api_url, serviceability_api_url
from modules.diagnostics.orange_health.booking_helpers import (
    apply_orange_health_response_to_booking_row,
    build_orange_health_order_payload,
    parse_orange_slot_time,
    slim_orange_health_slots,
)
from modules.diagnostics.orange_health.client import OrangeHealthApiError
from modules.diagnostics.orange_health.sync_log import log_orange_health_call
from modules.engagements.blood_bookings_access import apply_schedule, get_or_create_current, get_current_row, read_schedule_from_row
from modules.engagements.models import Engagement, EngagementParticipant
from modules.users.models import User
from common.phone import to_healthians_mobile
from modules.metsights.service import outbound_last_name

logger = logging.getLogger(__name__)


def _serviceability_url() -> str:
    return serviceability_api_url()


def _order_url() -> str:
    return order_api_url()


async def check_serviceability_at_location(
    db: AsyncSession,
    *,
    latitude: float,
    longitude: float,
    request_date: str | None = None,
    engagement_id: int | None = None,
    engagement_code: str | None = None,
) -> dict[str, Any]:
    req_date = request_date or (date.today() + timedelta(days=1)).isoformat()
    api_url = _serviceability_url()
    req = {"latitude": latitude, "longitude": longitude, "request_date": req_date}
    try:
        resp = await orange_health_client.check_serviceability(
            latitude=latitude,
            longitude=longitude,
            request_date=req_date,
        )
    except OrangeHealthApiError as exc:
        await log_orange_health_call(
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
        await log_orange_health_call(
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

    await log_orange_health_call(
        db,
        engagement_id=engagement_id,
        user_id=None,
        api_url=api_url,
        request_payload=req,
        response_payload=resp,
        status="success",
    )
    out = {
        "status": "success",
        "message": resp.get("status", "Location is serviceable"),
        "diagnostic_provider": "orange_health",
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
) -> dict[str, Any]:
    request_date = blood_collection_date.isoformat()
    api_url = _serviceability_url()
    req = {"latitude": latitude, "longitude": longitude, "request_date": request_date}
    await release_request_transaction(db)
    try:
        resp = await orange_health_client.check_serviceability(
            latitude=latitude,
            longitude=longitude,
            request_date=request_date,
        )
    except Exception as exc:
        await log_orange_health_call(
            db,
            engagement_id=engagement_id,
            user_id=None,
            api_url=api_url,
            request_payload=req,
            status="failed",
            error_message=str(exc),
        )
        out = {"status": "error", "message": str(exc)}
        if engagement_code:
            out["engagement_code"] = engagement_code
        return out

    await log_orange_health_call(
        db,
        engagement_id=engagement_id,
        user_id=None,
        api_url=api_url,
        request_payload=req,
        response_payload=resp,
        status="success",
    )
    slots_map = resp.get("slots") if isinstance(resp.get("slots"), dict) else {}
    slim = slim_orange_health_slots(slots_map)
    out = {"status": "success", "slots": slim, "diagnostic_provider": "orange_health"}
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
    slot_start = parse_orange_slot_time(slot_id if "T" in slot_id else slot_time_label)
    await apply_schedule(
        db,
        participant,
        engagement_date=blood_collection_date,
        slot_start_time=slot_start,
        blood_collection_time_slot_id=slot_id,
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
) -> dict[str, Any]:
    coll_row = await get_current_row(db, participant)
    sched = read_schedule_from_row(coll_row)
    slot_id = (sched["blood_collection_time_slot_id"] or "").strip()
    package_code = (pkg.external_package_code or "").strip()
    if not package_code or not slot_id:
        return {"user_id": user_id, "engagement_id": engagement_id, "status": "error", "message": "Missing slot or package code"}

    first_name = (user.first_name or "").strip()
    last_name = outbound_last_name(user.last_name)
    phone = to_healthians_mobile((user.phone or "").strip())
    if not first_name or len(phone) != 10 or user.age is None:
        return {
            "user_id": user_id,
            "engagement_id": engagement_id,
            "status": "error",
            "message": "Incomplete participant profile",
        }

    patient_name = f"{first_name} {last_name}".strip()
    address = (participant.address or engagement.address or "").strip()
    if not address:
        return {"user_id": user_id, "engagement_id": engagement_id, "status": "error", "message": "Missing address"}

    lat = participant.latitude if participant.latitude is not None else engagement.latitude
    lng = participant.longitude if participant.longitude is not None else engagement.longitude

    payload = build_orange_health_order_payload(
        participant_address=address,
        latitude=lat,
        longitude=lng,
        primary_name=patient_name,
        primary_phone=phone,
        slot_datetime=slot_id,
        partner_notes=partner_notes or "",
        user_id=user_id,
        patient_name=patient_name,
        patient_phone=phone,
        age=user.age,
        gender=user.gender or "",
        package_code=package_code,
    )

    await release_request_transaction(db)
    api_url = _order_url()
    try:
        resp = await orange_health_client.create_order(payload)
    except Exception as exc:
        await log_orange_health_call(
            db,
            engagement_id=engagement_id,
            user_id=user_id,
            api_url=api_url,
            request_payload=payload,
            status="failed",
            error_message=str(exc),
        )
        return {"user_id": user_id, "engagement_id": engagement_id, "status": "error", "message": str(exc)}

    await log_orange_health_call(
        db,
        engagement_id=engagement_id,
        user_id=user_id,
        api_url=api_url,
        request_payload=payload,
        response_payload=resp,
        status="success",
    )

    coll_row = await get_or_create_current(db, participant)
    apply_orange_health_response_to_booking_row(coll_row, resp, user_id=user_id)
    db.add(coll_row)
    await db.flush()

    request_id = str(resp.get("request_id") or "")
    return {
        "user_id": user_id,
        "engagement_id": engagement_id,
        "status": "success",
        "message": resp.get("status", "Booking placed"),
        "booking_id": request_id,
    }
