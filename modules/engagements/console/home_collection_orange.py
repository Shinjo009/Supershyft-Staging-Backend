"""Orange Health home-collection steps for engagement console."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from common.phone import to_healthians_mobile
from core.exceptions import AppError
from db.transaction import release_request_transaction
from modules.diagnostics.models import DiagnosticPackage
from modules.diagnostics.orange_health import client as orange_health_client
from modules.diagnostics.orange_health.booking_helpers import (
    apply_orange_health_response_to_booking_row,
    build_orange_health_order_payload,
    parse_orange_slot_time,
    slim_orange_health_slots,
)
from modules.diagnostics.orange_health.client import OrangeHealthApiError, order_api_url, serviceability_api_url
from modules.diagnostics.orange_health.sync_log import (
    finalize_orange_health_sync_log_isolated,
    log_orange_health_call,
    persist_orange_health_sync_log_isolated,
)
from modules.engagements.blood_bookings_access import apply_schedule, get_current_row, read_schedule_from_row
from modules.engagements.models import EngagementParticipant
from modules.metsights.service import outbound_last_name
from modules.users.models import User

logger = logging.getLogger(__name__)


def _serviceability_url() -> str:
    return serviceability_api_url()


def _order_url() -> str:
    return order_api_url()


async def check_serviceability(
    db: AsyncSession,
    *,
    engagement_id: int,
    user_id: int,
    participant: EngagementParticipant,
    latitude: float,
    longitude: float,
) -> dict[str, Any]:
    request_date = (date.today() + timedelta(days=1)).isoformat()
    api_url = _serviceability_url()
    req = {"latitude": latitude, "longitude": longitude, "request_date": request_date}
    try:
        resp = await orange_health_client.check_serviceability(
            latitude=latitude,
            longitude=longitude,
            request_date=request_date,
        )
    except OrangeHealthApiError as exc:
        await log_orange_health_call(
            db,
            engagement_id=engagement_id,
            user_id=user_id,
            api_url=api_url,
            request_payload=req,
            response_payload=exc.body if isinstance(exc.body, dict) else None,
            status="failed",
            error_message=str(exc),
        )
        if exc.status_code == 404:
            raise AppError(
                status_code=422,
                error_code="LOCATION_NOT_SERVICEABLE",
                message=str(exc),
            ) from exc
        raise AppError(status_code=502, error_code="ORANGE_HEALTH_SERVICEABILITY_FAILED", message=str(exc)) from exc
    except Exception as exc:
        logger.exception("Orange Health serviceability failed for user %s", user_id)
        await log_orange_health_call(
            db,
            engagement_id=engagement_id,
            user_id=user_id,
            api_url=api_url,
            request_payload=req,
            status="failed",
            error_message=str(exc),
        )
        raise AppError(status_code=502, error_code="ORANGE_HEALTH_SERVICEABILITY_FAILED", message=str(exc)) from exc

    await log_orange_health_call(
        db,
        engagement_id=engagement_id,
        user_id=user_id,
        api_url=api_url,
        request_payload=req,
        response_payload=resp,
        status="success",
    )
    return {
        "status": "serviceable",
        "message": resp.get("status", "Location is serviceable"),
        "engagement_id": engagement_id,
        "user_id": user_id,
        "diagnostic_provider": "orange_health",
    }


async def fetch_slots(
    db: AsyncSession,
    *,
    engagement_id: int,
    user_id: int,
    participant: EngagementParticipant,
    blood_collection_date: date,
) -> dict[str, Any]:
    if participant.latitude is None or participant.longitude is None:
        raise AppError(status_code=422, error_code="MISSING_LOCATION", message="Service availability has not been checked yet")

    request_date = blood_collection_date.isoformat()
    api_url = _serviceability_url()
    req = {
        "latitude": float(participant.latitude),
        "longitude": float(participant.longitude),
        "request_date": request_date,
    }
    await release_request_transaction(db)
    try:
        resp = await orange_health_client.check_serviceability(
            latitude=req["latitude"],
            longitude=req["longitude"],
            request_date=request_date,
        )
    except OrangeHealthApiError as exc:
        await log_orange_health_call(
            db,
            engagement_id=engagement_id,
            user_id=user_id,
            api_url=api_url,
            request_payload=req,
            response_payload=exc.body if isinstance(exc.body, dict) else None,
            status="failed",
            error_message=str(exc),
        )
        raise AppError(status_code=422, error_code="SLOTS_FETCH_FAILED", message=str(exc)) from exc
    except Exception as exc:
        await log_orange_health_call(
            db,
            engagement_id=engagement_id,
            user_id=user_id,
            api_url=api_url,
            request_payload=req,
            status="failed",
            error_message=str(exc),
        )
        raise AppError(status_code=502, error_code="ORANGE_HEALTH_SLOTS_FAILED", message=str(exc)) from exc

    await log_orange_health_call(
        db,
        engagement_id=engagement_id,
        user_id=user_id,
        api_url=api_url,
        request_payload=req,
        response_payload=resp,
        status="success",
    )
    slots_map = resp.get("slots") if isinstance(resp.get("slots"), dict) else {}
    slim_slots = slim_orange_health_slots(slots_map)
    return {
        "status": "success",
        "slots": slim_slots,
        "engagement_id": engagement_id,
        "user_id": user_id,
        "diagnostic_provider": "orange_health",
    }


async def lock_slot(
    db: AsyncSession,
    *,
    participant: EngagementParticipant,
    blood_collection_date: date,
    blood_collection_time_slot_id: str,
    blood_collection_time_slot: str,
    engagement_id: int,
    user_id: int,
) -> dict[str, Any]:
    slot_id = blood_collection_time_slot_id.strip()
    try:
        slot_start_time = parse_orange_slot_time(
            slot_id if "T" in slot_id else blood_collection_time_slot
        )
    except ValueError as exc:
        raise AppError(status_code=422, error_code="INVALID_SLOT_TIME", message=str(exc)) from exc

    await apply_schedule(
        db,
        participant,
        engagement_date=blood_collection_date,
        slot_start_time=slot_start_time,
        blood_collection_time_slot_id=slot_id,
    )
    return {
        "status": "success",
        "message": "Slot confirmed",
        "slot_id": slot_id,
        "engagement_id": engagement_id,
        "user_id": user_id,
        "diagnostic_provider": "orange_health",
    }


async def create_booking(
    db: AsyncSession,
    *,
    engagement_id: int,
    user_id: int,
    participant: EngagementParticipant,
    user: User,
    pkg: DiagnosticPackage,
    partner_notes: str = "",
) -> dict[str, Any]:
    coll = await get_current_row(db, participant)
    sched = read_schedule_from_row(coll)
    slot_id = (sched["blood_collection_time_slot_id"] or "").strip()
    if not slot_id:
        raise AppError(status_code=422, error_code="SLOT_NOT_LOCKED", message="Blood collection slot is not locked")

    package_code = (pkg.external_package_code or "").strip()
    if not package_code:
        raise AppError(status_code=422, error_code="INVALID_STATE", message="Diagnostic package has no external package code")

    first_name = (user.first_name or "").strip()
    last_name = outbound_last_name(user.last_name)
    phone_raw = (user.phone or "").strip()
    if not first_name or not phone_raw or user.age is None:
        raise AppError(
            status_code=422,
            error_code="INCOMPLETE_PARTICIPANT_PROFILE",
            message="Participant profile is missing required fields (first name, phone, age)",
        )
    phone = to_healthians_mobile(phone_raw)
    if len(phone) != 10:
        raise AppError(
            status_code=422,
            error_code="INVALID_PHONE",
            message="Participant phone must be a valid 10-digit mobile number",
        )

    patient_name = f"{first_name} {last_name}".strip()
    address = (participant.address or "").strip()
    if not address:
        raise AppError(status_code=422, error_code="MISSING_ADDRESS", message="Participant address is required")

    booking_payload = build_orange_health_order_payload(
        participant_address=address,
        latitude=participant.latitude,
        longitude=participant.longitude,
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
    booking_url = _order_url()
    log_id = await persist_orange_health_sync_log_isolated(
        engagement_id=engagement_id,
        user_id=user_id,
        api_url=booking_url,
        request_payload=booking_payload,
        status="pending",
    )
    try:
        booking_response = await orange_health_client.create_order(booking_payload)
        await finalize_orange_health_sync_log_isolated(
            sync_log_id=log_id,
            status="success",
            response_payload=booking_response,
        )
    except OrangeHealthApiError as exc:
        await finalize_orange_health_sync_log_isolated(
            sync_log_id=log_id,
            status="failed",
            response_payload=exc.body if isinstance(exc.body, dict) else None,
            error_message=str(exc),
        )
        raise AppError(
            status_code=422,
            error_code="ORANGE_HEALTH_BOOKING_FAILED",
            message=str(exc),
        ) from exc
    except Exception as exc:
        await finalize_orange_health_sync_log_isolated(
            sync_log_id=log_id,
            status="failed",
            error_message=str(exc),
        )
        raise AppError(status_code=502, error_code="ORANGE_HEALTH_BOOKING_FAILED", message=str(exc)) from exc

    coll_row = await get_current_row(db, participant)
    apply_orange_health_response_to_booking_row(coll_row, booking_response, user_id=user_id)
    db.add(coll_row)
    await db.flush()

    request_id = str(booking_response.get("request_id") or "")
    return {
        "status": booking_response.get("status"),
        "message": "Orange Health booking placed",
        "booking_id": request_id,
        "request_id": request_id,
        "token": booking_response.get("token"),
        "orders": booking_response.get("orders"),
        "engagement_participant_id": participant.engagement_participant_id,
        "user_id": user_id,
        "engagement_id": engagement_id,
        "diagnostic_provider": "orange_health",
    }
