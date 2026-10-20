"""Public diagnostic provider routes (no authentication)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from common.responses import success_response
from core.rate_limit import limiter
from db.session import get_db
from modules.diagnostics.public_schemas import (
    PublicAvailableSlotsRequest,
    PublicServiceabilityRequest,
)
from modules.diagnostics import public_service

router = APIRouter(prefix="/diagnostics/public", tags=["diagnostics-public"])


@router.post("/serviceability")
@limiter.limit("10/minute")
async def public_serviceability(
    payload: PublicServiceabilityRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await public_service.public_check_serviceability(
        db,
        provider=payload.provider,
        address_line=payload.address_line,
        landmark=payload.landmark,
        city=payload.city,
        pincode=payload.pincode,
        latitude=payload.latitude,
        longitude=payload.longitude,
        diagnostic_package_id=payload.diagnostic_package_id,
    )
    return success_response(result)


@router.post("/available-slots")
@limiter.limit("10/minute")
async def public_available_slots(
    payload: PublicAvailableSlotsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await public_service.public_available_slots(
        db,
        provider=payload.provider,
        slot_date=payload.slot_date,
        diagnostic_package_id=payload.diagnostic_package_id,
        zone_id=payload.zone_id,
        latitude=payload.latitude,
        longitude=payload.longitude,
        pincode=payload.pincode,
        has_female_patient=payload.has_female_patient,
    )
    return success_response(result)
