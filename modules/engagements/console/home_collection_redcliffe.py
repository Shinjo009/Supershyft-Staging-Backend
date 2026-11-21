"""Redcliffe Labs home-collection steps for engagement console."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from common.phone import to_healthians_mobile
from core.exceptions import AppError
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
from modules.diagnostics.redcliffe.sync_log import (
    finalize_redcliffe_sync_log_isolated,
    log_redcliffe_call,
    persist_redcliffe_sync_log_isolated,
)
from modules.engagements.blood_bookings_access import apply_schedule, get_current_row, read_schedule_from_row
from modules.engagements.models import EngagementParticipant
from modules.metsights.service import outbound_last_name
from modules.users.models import User

logger = logging.getLogger(__name__)


async def check_serviceability(
    db: AsyncSession,
    *,
    engagement_id: int,
    user_id: int,
    participant: EngagementParticipant,
    latitude: float,
    longitude: float,
) -> dict[str, Any]:
    api_url = serviceability_api_url()
    req = {"latitude": latitude, "longitude": longitude}
    try:
        resp = await redcliffe_client.check_location_serviceable(latitude=latitude, longitude=longitude)
    except RedcliffeApiError as exc:
        await log_redcliffe_call(
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
        raise AppError(status_code=502, error_code="REDCLIFFE_SERVICEABILITY_FAILED", message=str(exc)) from exc
    except Exception as exc:
        logger.exception("Redcliffe serviceability failed for user %s", user_id)
        await log_redcliffe_call(
            db,
            engagement_id=engagement_id,
            user_id=user_id,
            api_url=api_url,
            request_payload=req,
            status="failed",
            error_message=str(exc),
        )
        raise AppError(status_code=502, error_code="REDCLIFFE_SERVICEABILITY_FAILED", message=str(exc)) from exc

    serviceable = is_serviceable_response(resp)
    await log_redcliffe_call(
        db,
        engagement_id=engagement_id,
        user_id=user_id,
        api_url=api_url,
        request_payload=req,
        response_payload=resp,
        status="success" if serviceable else "failed",
        error_message=None if serviceable else resp.get("message"),
    )
    if not serviceable:
        raise AppError(
            status_code=422,
            error_code="LOCATION_NOT_SERVICEABLE",
            message=resp.get("message") or "Location is non-serviceable",
        )
    return {
        "status": "serviceable",
        "message": resp.get("message", "Location is serviceable"),
        "engagement_id": engagement_id,
        "user_id": user_id,
        "diagnostic_provider": "redcliffe",
    }


async def fetch_slots(
    db: AsyncSession,
    *,
    engagement_id: int,
    user_id: int,
    participant: EngagementParticipant,
    blood_collection_date: date,
    customer_gender: str | None = None,
) -> dict[str, Any]:
    if participant.latitude is None or participant.longitude is None:
        raise AppError(status_code=422, error_code="MISSING_LOCATION", message="Service availability has not been checked yet")

    collection_date = blood_collection_date.isoformat()
    api_url = time_slot_list_api_url()
    req = {
        "collection_date": collection_date,
        "latitude": float(participant.latitude),
        "longitude": float(participant.longitude),
    }
    if customer_gender:
        req["customer_gender"] = customer_gender

    await release_request_transaction(db)
    try:
        resp = await redcliffe_client.get_time_slot_list(
            collection_date=collection_date,
            latitude=float(participant.latitude),
            longitude=float(participant.longitude),
            customer_gender=customer_gender,
        )
    except RedcliffeApiError as exc:
        await log_redcliffe_call(
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
        await log_redcliffe_call(
            db,
            engagement_id=engagement_id,
            user_id=user_id,
            api_url=api_url,
            request_payload=req,
            status="failed",
            error_message=str(exc),
        )
        raise AppError(status_code=502, error_code="REDCLIFFE_SLOTS_FAILED", message=str(exc)) from exc

    await log_redcliffe_call(
        db,
        engagement_id=engagement_id,
        user_id=user_id,
        api_url=api_url,
        request_payload=req,
        response_payload=resp,
        status="success",
    )
    raw = resp.get("results")
    if raw is None:
        raw = resp.get("data")
    slots_list = raw if isinstance(raw, list) else []
    slim_slots = slim_redcliffe_slots(slots_list, collection_date=blood_collection_date)
    partner_message = (resp.get("message") or "").strip() or None
    return {
        "status": "success",
        "slots": slim_slots,
        "engagement_id": engagement_id,
        "user_id": user_id,
        "diagnostic_provider": "redcliffe",
        "partner_message": partner_message if not slim_slots else None,
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
        int(slot_id)
    except ValueError as exc:
        raise AppError(status_code=422, error_code="INVALID_SLOT_TIME", message="Invalid Redcliffe slot id") from exc
    try:
        slot_start_time = parse_redcliffe_slot_time(blood_collection_time_slot)
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
        "diagnostic_provider": "redcliffe",
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
    is_credit: bool = True,
) -> dict[str, Any]:
    _ = partner_notes
    coll = await get_current_row(db, participant)
    sched = read_schedule_from_row(coll)
    slot_id = (sched["blood_collection_time_slot_id"] or "").strip()
    if not slot_id:
        raise AppError(status_code=422, error_code="SLOT_NOT_LOCKED", message="Blood collection slot is not locked")
    collection_date = sched["engagement_date"]
    if collection_date is None:
        raise AppError(status_code=422, error_code="SLOT_NOT_LOCKED", message="Blood collection date is not set")

    package_code = (pkg.external_package_code or "").strip()
    if not package_code:
        raise AppError(status_code=422, error_code="INVALID_STATE", message="Diagnostic package has no external package code")

    first_name = (user.first_name or "").strip()
    last_name = outbound_last_name(user.last_name)
    phone_raw = (user.phone or "").strip()
    email = (user.email or "").strip()
    if not first_name or not phone_raw or user.age is None or not email or "@" not in email:
        raise AppError(
            status_code=422,
            error_code="INCOMPLETE_PARTICIPANT_PROFILE",
            message="Participant profile is missing required fields (first name, phone, age, email)",
        )
    try:
        redcliffe_gender(user.gender)
    except ValueError as exc:
        raise AppError(
            status_code=422,
            error_code="INVALID_GENDER",
            message="Participant gender must be male or female for Redcliffe",
        ) from exc

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
    pincode = (participant.pincode or "").strip()
    if not pincode:
        raise AppError(status_code=422, error_code="MISSING_ADDRESS", message="Participant pincode is required")
    if participant.latitude is None or participant.longitude is None:
        raise AppError(status_code=422, error_code="MISSING_LOCATION", message="Participant location is required")

    try:
        collection_slot = int(slot_id)
    except ValueError as exc:
        raise AppError(status_code=422, error_code="INVALID_SLOT_TIME", message="Invalid Redcliffe slot id") from exc

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
        customer_landmark=(participant.landmark or address).strip(),
        pincode=pincode,
        latitude=float(participant.latitude),
        longitude=float(participant.longitude),
        reference_data=f"{engagement_id}:{user_id}",
        is_credit=is_credit,
    )

    await release_request_transaction(db)
    create_url = center_create_booking_api_url()
    log_id = await persist_redcliffe_sync_log_isolated(
        engagement_id=engagement_id,
        user_id=user_id,
        api_url=create_url,
        request_payload=create_payload,
        status="pending",
    )
    try:
        create_resp = await redcliffe_client.center_create_booking(create_payload)
        await finalize_redcliffe_sync_log_isolated(
            sync_log_id=log_id,
            status="success",
            response_payload=create_resp,
        )
    except RedcliffeApiError as exc:
        await finalize_redcliffe_sync_log_isolated(
            sync_log_id=log_id,
            status="failed",
            response_payload=exc.body if isinstance(exc.body, dict) else None,
            error_message=str(exc),
        )
        raise AppError(
            status_code=422,
            error_code="REDCLIFFE_BOOKING_FAILED",
            message=str(exc),
        ) from exc
    except Exception as exc:
        await finalize_redcliffe_sync_log_isolated(
            sync_log_id=log_id,
            status="failed",
            error_message=str(exc),
        )
        raise AppError(status_code=502, error_code="REDCLIFFE_BOOKING_FAILED", message=str(exc)) from exc

    temp_booking_id = extract_redcliffe_booking_id(create_resp)
    if not temp_booking_id:
        raise AppError(
            status_code=502,
            error_code="REDCLIFFE_BOOKING_FAILED",
            message="Redcliffe did not return a booking id",
        )

    confirm_url = center_confirm_booking_api_url()
    confirm_payload = {"booking_id": temp_booking_id, "is_confirmed": True}
    confirm_log_id = await persist_redcliffe_sync_log_isolated(
        engagement_id=engagement_id,
        user_id=user_id,
        api_url=confirm_url,
        request_payload=confirm_payload,
        status="pending",
    )
    try:
        confirm_resp = await redcliffe_client.center_confirm_booking(
            booking_id=temp_booking_id,
            is_confirmed=True,
        )
        await finalize_redcliffe_sync_log_isolated(
            sync_log_id=confirm_log_id,
            status="success",
            response_payload=confirm_resp,
        )
    except RedcliffeApiError as exc:
        await finalize_redcliffe_sync_log_isolated(
            sync_log_id=confirm_log_id,
            status="failed",
            response_payload=exc.body if isinstance(exc.body, dict) else None,
            error_message=str(exc),
        )
        raise AppError(
            status_code=422,
            error_code="REDCLIFFE_BOOKING_FAILED",
            message=str(exc),
        ) from exc
    except Exception as exc:
        await finalize_redcliffe_sync_log_isolated(
            sync_log_id=confirm_log_id,
            status="failed",
            error_message=str(exc),
        )
        raise AppError(status_code=502, error_code="REDCLIFFE_BOOKING_FAILED", message=str(exc)) from exc

    coll_row = await get_current_row(db, participant)
    apply_redcliffe_response_to_booking_row(
        coll_row,
        create_response=create_resp,
        confirm_response=confirm_resp,
    )
    db.add(coll_row)
    await db.flush()

    final_id = extract_redcliffe_booking_id(confirm_resp) or temp_booking_id
    return {
        "status": "success",
        "message": confirm_resp.get("message", "Redcliffe booking placed"),
        "booking_id": final_id,
        "engagement_participant_id": participant.engagement_participant_id,
        "user_id": user_id,
        "engagement_id": engagement_id,
        "diagnostic_provider": "redcliffe",
    }