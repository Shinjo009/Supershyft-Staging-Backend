"""Public diagnostic provider helpers (no engagement rows)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppError
from modules.bookings.service import (
    _get_diagnostic_package,
    _get_healthians_token,
    _healthians_zone_id,
    _is_healthians,
    _slim_healthians_slot,
)
from modules.bookings import orange_health_flow
from modules.diagnostics.external_codes import healthians_package_deal_id
from modules.diagnostics.healthians import client as healthians_client
from modules.diagnostics.orange_health.booking_helpers import is_orange_health
from modules.geocoding.client import enrich_location_fields
from modules.platform_settings.repository import PlatformSettingsRepository

logger = logging.getLogger(__name__)


def _normalize_provider(provider: str) -> str:
    return (provider or "").strip().lower()


async def public_check_serviceability(
    db: AsyncSession,
    *,
    provider: str,
    address_line: str,
    landmark: str | None,
    city: str,
    pincode: str,
    latitude: float | None,
    longitude: float | None,
    diagnostic_package_id: int | None,
) -> dict[str, Any]:
    prov = _normalize_provider(provider)
    if prov == "orange_health":
        if latitude is None or longitude is None:
            primary = await PlatformSettingsRepository().resolve_geocoding_provider(db)
            location = await enrich_location_fields(
                address=address_line,
                landmark=landmark,
                city=city,
                pincode=pincode,
                latitude=latitude,
                longitude=longitude,
                primary=primary,
            )
            latitude = location.get("latitude")
            longitude = location.get("longitude")
        if latitude is None or longitude is None:
            raise AppError(status_code=422, error_code="INVALID_INPUT", message="Location coordinates are required")
        result = await orange_health_flow.check_serviceability_at_location(
            db,
            latitude=float(latitude),
            longitude=float(longitude),
            engagement_id=None,
        )
        return {
            "serviceable": result.get("status") == "success",
            "message": result.get("message"),
            "provider": prov,
            "data": result,
        }

    if prov != "healthians":
        raise AppError(status_code=422, error_code="INVALID_PROVIDER", message="Unsupported diagnostic provider")

    if diagnostic_package_id is not None:
        pkg = await _get_diagnostic_package(db, diagnostic_package_id)
        if not _is_healthians(pkg):
            raise AppError(status_code=422, error_code="INVALID_PROVIDER", message="Package is not a Healthians package")

    primary = await PlatformSettingsRepository().resolve_geocoding_provider(db)
    location = await enrich_location_fields(
        address=address_line,
        landmark=landmark,
        city=city,
        pincode=pincode,
        latitude=latitude,
        longitude=longitude,
        primary=primary,
    )
    lat = location.get("latitude")
    lng = location.get("longitude")
    if lat is None or lng is None:
        raise AppError(status_code=422, error_code="INVALID_INPUT", message="Could not resolve location coordinates")

    access_token = await _get_healthians_token()
    try:
        resp = await healthians_client.check_serviceability_by_location_v2(
            access_token,
            latitude=str(lat),
            longitude=str(lng),
            zipcode=pincode,
        )
    except Exception as exc:
        logger.exception("Public Healthians serviceability failed")
        raise AppError(status_code=502, error_code="HEALTHIANS_API_ERROR", message=str(exc)) from exc

    zone_id = _healthians_zone_id(resp)
    return {
        "serviceable": bool(resp.get("status")),
        "message": resp.get("message"),
        "provider": prov,
        "zone_id": str(zone_id) if zone_id else None,
        "latitude": lat,
        "longitude": lng,
        "data": resp.get("data"),
    }


async def public_available_slots(
    db: AsyncSession,
    *,
    provider: str,
    slot_date: date,
    diagnostic_package_id: int,
    zone_id: str | None,
    latitude: float | None,
    longitude: float | None,
    pincode: str | None,
    has_female_patient: bool,
) -> dict[str, Any]:
    prov = _normalize_provider(provider)
    pkg = await _get_diagnostic_package(db, diagnostic_package_id)

    if prov == "orange_health" or _is_orange_health(pkg):
        if latitude is None or longitude is None:
            raise AppError(status_code=422, error_code="INVALID_INPUT", message="latitude and longitude are required")
        slot_resp = await orange_health_flow.fetch_slots_for_location(
            db,
            blood_collection_date=slot_date,
            latitude=float(latitude),
            longitude=float(longitude),
            engagement_id=None,
        )
        if slot_resp.get("status") != "success":
            raise AppError(
                status_code=422,
                error_code="SLOTS_UNAVAILABLE",
                message=slot_resp.get("message", "Failed to fetch slots"),
            )
        return {"provider": prov, "slots": slot_resp.get("slots") or []}

    if prov != "healthians" and not _is_healthians(pkg):
        raise AppError(status_code=422, error_code="INVALID_PROVIDER", message="Unsupported diagnostic provider")

    amount = float(pkg.original_price) if pkg.original_price else 0
    deal_id = healthians_package_deal_id(pkg.external_package_code)
    access_token = await _get_healthians_token()
    payload = {
        "slot_date": slot_date.isoformat(),
        "zone_id": str(zone_id or ""),
        "lat": str(latitude or ""),
        "long": str(longitude or ""),
        "zipcode": pincode or "",
        "get_ppmc_slots": 0,
        "has_female_patient": 1 if has_female_patient else 0,
        "amount": amount,
        "package": [{"deal_id": [deal_id]}],
    }
    try:
        resp = await healthians_client.get_slots_by_location(access_token, payload)
    except Exception as exc:
        logger.exception("Public Healthians slots failed")
        raise AppError(status_code=502, error_code="HEALTHIANS_API_ERROR", message=str(exc)) from exc

    if not resp.get("status"):
        raise AppError(
            status_code=422,
            error_code="SLOTS_UNAVAILABLE",
            message=resp.get("message", "Failed to fetch slots"),
        )
    raw_slots = resp.get("data", []) or []
    return {
        "provider": "healthians",
        "slots": [_slim_healthians_slot(slot) for slot in raw_slots if isinstance(slot, dict)],
    }


async def public_lock_slot(
    db: AsyncSession,
    *,
    provider: str,
    slot_id: str,
    slot_date: date,
    slot_time: str,
    vendor_billing_user_id: str,
    latitude: float | None,
    longitude: float | None,
    pincode: str | None,
    zone_id: str | None,
) -> dict[str, Any]:
    prov = _normalize_provider(provider)
    if prov in {"orange_health", "orange"}:
        return {
            "provider": prov,
            "locked": False,
            "message": "Slot locking is not required for this provider",
            "slot_id": slot_id,
        }

    if prov != "healthians":
        raise AppError(status_code=422, error_code="INVALID_PROVIDER", message="Unsupported diagnostic provider")

    access_token = await _get_healthians_token()
    billing_id = (vendor_billing_user_id or "public").strip() or "public"
    try:
        resp = await healthians_client.freeze_slot_v1(
            access_token,
            slot_id=slot_id,
            vendor_billing_user_id=billing_id,
        )
    except Exception as exc:
        logger.exception("Public Healthians lock slot failed")
        raise AppError(status_code=502, error_code="HEALTHIANS_API_ERROR", message=str(exc)) from exc

    if not resp.get("status"):
        raise AppError(
            status_code=422,
            error_code="SLOT_LOCK_FAILED",
            message=resp.get("message", "Failed to lock slot"),
        )
    return {
        "provider": "healthians",
        "locked": True,
        "slot_id": slot_id,
        "message": resp.get("message", "Slot locked"),
        "data": resp.get("data"),
    }
