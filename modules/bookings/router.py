"""Authenticated batch booking endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from common.responses import success_response
from core.dependencies import get_current_user
from core.rate_limit import limiter
from db.session import get_db
from modules.bookings.schemas import (
    AvailableSlotsRequest,
    BookPayRequest,
    CancelBookingRequest,
    CheckServiceabilityRequest,
    LockSlotRequest,
    CodeAvailableSlotsRequest,
    CodeLockSlotRequest,
    PublicAvailableSlotsRequest,
    PublicCheckServiceabilityRequest,
    PublicLockSlotRequest,
    VerifyAndBookRequest,
)
from modules.bookings import service as booking_service
from modules.engagements.dependencies import get_engagements_repository, get_engagements_service
from modules.engagements.repository import EngagementsRepository
from modules.engagements.service import EngagementsService
from modules.platform_settings.dependencies import get_platform_settings_service_readonly
from modules.platform_settings.service import PlatformSettingsService


router = APIRouter(prefix="/book", tags=["bookings"])


@router.post("/pay")
@limiter.limit("5/minute")
async def book_pay(
    payload: BookPayRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from core.network import get_client_ip

    members = [{"user_id": m.user_id, "engagement_id": m.engagement_id} for m in payload.members]
    result = await booking_service.create_pay_order_for_draft_engagements(
        db,
        members=members,
        payer_user_id=current_user.user_id,
        discount_code=payload.discount_code,
        client_ip=get_client_ip(request),
    )
    await db.commit()
    return success_response(result)


@router.post("/bio-ai")
@limiter.limit("5/minute")
async def book_bio_ai_batch(
    payload: VerifyAndBookRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    engagements_service: EngagementsService = Depends(get_engagements_service),
):
    result = await booking_service.verify_and_finalize_draft_bookings(
        db,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_signature=payload.razorpay_signature,
        caller_user_id=current_user.user_id,
        engagement_type_code="bio_ai",
        engagements_service=engagements_service,
    )
    await db.commit()
    return success_response(result)


@router.post("/blood-test")
@limiter.limit("5/minute")
async def book_blood_test_batch(
    payload: VerifyAndBookRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    engagements_service: EngagementsService = Depends(get_engagements_service),
):
    result = await booking_service.verify_and_finalize_draft_bookings(
        db,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_signature=payload.razorpay_signature,
        caller_user_id=current_user.user_id,
        engagement_type_code="blood_test",
        engagements_service=engagements_service,
    )
    await db.commit()
    return success_response(result)


@router.post("/cancel/bio-ai")
@limiter.limit("5/minute")
async def cancel_bio_ai_bookings(
    payload: CancelBookingRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    repository: EngagementsRepository = Depends(get_engagements_repository),
):
    members = [
        {"user_id": m.user_id, "engagement_id": m.engagement_id, "remarks": m.remarks}
        for m in payload.members
    ]
    result = await booking_service.cancel_healthians_bookings_batch(
        db,
        members=members,
        caller_user_id=current_user.user_id,
        repository=repository,
    )
    await db.commit()
    return success_response({"members": result})


@router.post("/cancel/blood-test")
@limiter.limit("5/minute")
async def cancel_blood_test_bookings(
    payload: CancelBookingRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    repository: EngagementsRepository = Depends(get_engagements_repository),
):
    members = [
        {"user_id": m.user_id, "engagement_id": m.engagement_id, "remarks": m.remarks}
        for m in payload.members
    ]
    result = await booking_service.cancel_healthians_bookings_batch(
        db,
        members=members,
        caller_user_id=current_user.user_id,
        repository=repository,
    )
    await db.commit()
    return success_response({"members": result})


@router.get("/me/drafts")
async def get_my_drafts(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    engagements = await booking_service.get_user_draft_engagements(
        db, user_id=current_user.user_id
    )
    return success_response({"engagements": engagements})


@router.post("/check-service-availability")
@limiter.limit("5/minute")
async def check_service_availability(
    payload: CheckServiceabilityRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    engagements_service: EngagementsService = Depends(get_engagements_service),
):
    members = [
        {
            "user_id": m.user_id,
            "address_line": m.address_line,
            "landmark": m.landmark,
            "city": m.city,
            "pincode": m.pincode,
            "diagnostic_package_id": m.diagnostic_package_id,
        }
        for m in payload.members
    ]
    result = await booking_service.check_service_availability(
        db, members=members, engagements_service=engagements_service,
        booked_by_user_id=current_user.user_id,
    )
    await db.commit()
    return success_response({"members": result})


@router.post("/available-slots")
@limiter.limit("10/minute")
async def get_available_slots(
    payload: AvailableSlotsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    members = [
        {
            "user_id": m.user_id,
            "engagement_id": m.engagement_id,
            "blood_collection_date": m.blood_collection_date,
        }
        for m in payload.members
    ]
    result = await booking_service.get_available_slots(db, members=members)
    await db.commit()
    return success_response({"members": result})


@router.post("/lock")
@limiter.limit("5/minute")
async def lock_slots(
    payload: LockSlotRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    members = [
        {
            "user_id": m.user_id,
            "engagement_id": m.engagement_id,
            "blood_collection_date": m.blood_collection_date,
            "blood_collection_time_slot_id": m.blood_collection_time_slot_id,
            "blood_collection_time_slot": m.blood_collection_time_slot,
        }
        for m in payload.members
    ]
    result = await booking_service.lock_slots(db, members=members)
    await db.commit()
    return success_response({"members": result})


@router.post("/public/check-service-availability")
@limiter.limit("5/minute")
async def public_check_service_availability(
    payload: PublicCheckServiceabilityRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    platform_settings_service: PlatformSettingsService = Depends(get_platform_settings_service_readonly),
):
    result = await booking_service.public_check_service_availability(
        db,
        address_line=payload.address_line,
        landmark=payload.landmark,
        city=payload.city,
        pincode=payload.pincode,
        platform_settings_service=platform_settings_service,
    )
    await db.commit()
    return success_response(result)


@router.post("/code/{engagement_code}/check-service-availability")
@limiter.limit("5/minute")
async def code_check_service_availability(
    engagement_code: str,
    payload: PublicCheckServiceabilityRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await booking_service.code_check_service_availability(
        db,
        engagement_code=engagement_code,
        address_line=payload.address_line,
        landmark=payload.landmark,
        city=payload.city,
        pincode=payload.pincode,
    )
    await db.commit()
    return success_response(result)


@router.post("/public/available-slots")
@limiter.limit("10/minute")
async def public_get_available_slots(
    payload: PublicAvailableSlotsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    platform_settings_service: PlatformSettingsService = Depends(get_platform_settings_service_readonly),
):
    result = await booking_service.public_get_available_slots(
        db,
        address_line=payload.address_line,
        city=payload.city,
        pincode=payload.pincode,
        blood_collection_date=payload.blood_collection_date,
        platform_settings_service=platform_settings_service,
    )
    await db.commit()
    return success_response(result)


@router.post("/code/{engagement_code}/available-slots")
@limiter.limit("10/minute")
async def code_get_available_slots(
    engagement_code: str,
    payload: CodeAvailableSlotsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await booking_service.code_get_available_slots(
        db,
        engagement_code=engagement_code,
        address_line=payload.address_line,
        city=payload.city,
        pincode=payload.pincode,
        blood_collection_date=payload.blood_collection_date,
    )
    await db.commit()
    return success_response(result)


@router.post("/public/lock")
@limiter.limit("5/minute")
async def public_lock_slot(
    payload: PublicLockSlotRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await booking_service.public_lock_slot(
        db,
        city=payload.city,
        pincode=payload.pincode,
        user_id=payload.user_id,
        blood_collection_date=payload.blood_collection_date,
        blood_collection_time_slot_id=payload.blood_collection_time_slot_id,
        blood_collection_time_slot=payload.blood_collection_time_slot,
    )
    await db.commit()
    return success_response(result)


@router.post("/code/{engagement_code}/lock")
@limiter.limit("5/minute")
async def code_lock_slot(
    engagement_code: str,
    payload: CodeLockSlotRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await booking_service.code_lock_slot(
        db,
        engagement_code=engagement_code,
        address_line=payload.address_line,
        landmark=payload.landmark,
        city=payload.city,
        pincode=payload.pincode,
        user_id=payload.user_id,
        blood_collection_date=payload.blood_collection_date,
        blood_collection_time_slot_id=payload.blood_collection_time_slot_id,
        blood_collection_time_slot=payload.blood_collection_time_slot,
    )
    await db.commit()
    return success_response(result)
