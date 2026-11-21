"""Redcliffe Labs serviceability orchestration with sync logging."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.audit.cron_sync_logging import sanitize_response_payload
from modules.diagnostics.redcliffe.booking_helpers import build_redcliffe_place_query
from modules.diagnostics.redcliffe import client as redcliffe_client
from modules.diagnostics.redcliffe.client import RedcliffeApiError
from modules.diagnostics.redcliffe.sync_log import (
    finalize_redcliffe_sync_log_isolated,
    log_redcliffe_call,
    persist_redcliffe_sync_log_isolated,
)

logger = logging.getLogger(__name__)


def _sanitize(body: Any) -> dict[str, Any] | None:
    return sanitize_response_payload(body)


async def _tracked_call(
    *,
    api_url: str,
    request_payload: dict,
    call,
) -> dict[str, Any]:
    sync_log_id = await persist_redcliffe_sync_log_isolated(
        engagement_id=None,
        user_id=None,
        api_url=api_url,
        request_payload=request_payload,
        status="pending",
    )
    try:
        result = await call()
        await finalize_redcliffe_sync_log_isolated(
            sync_log_id=sync_log_id,
            status="success",
            response_payload=_sanitize(result),
        )
        return result
    except RedcliffeApiError as exc:
        await finalize_redcliffe_sync_log_isolated(
            sync_log_id=sync_log_id,
            status="failed",
            response_payload=_sanitize(exc.body),
            error_message=str(exc),
        )
        raise
    except Exception as exc:
        logger.exception("Redcliffe API call failed")
        await finalize_redcliffe_sync_log_isolated(
            sync_log_id=sync_log_id,
            status="failed",
            error_message=str(exc),
        )
        raise


async def search_area(*, place_query: str) -> dict[str, Any]:
    query = place_query.strip()
    api_url = redcliffe_client.search_area_api_url()
    req = {"place_query": query}
    return await _tracked_call(
        api_url=api_url,
        request_payload=req,
        call=lambda: redcliffe_client.search_area(place_query=query),
    )


async def get_coordinates(*, eloc: str) -> dict[str, Any]:
    code = eloc.strip()
    api_url = redcliffe_client.coordinates_api_url()
    req = {"eloc": code}
    return await _tracked_call(
        api_url=api_url,
        request_payload=req,
        call=lambda: redcliffe_client.get_coordinates(eloc=code),
    )


def _first_search_result(search_data: dict[str, Any]) -> dict[str, Any] | None:
    raw = search_data.get("results")
    if not isinstance(raw, list):
        return None
    for item in raw:
        if isinstance(item, dict) and (item.get("eloc") or "").strip():
            return item
    return None


def _geocoded_from_redcliffe(search_item: dict[str, Any], coords: dict[str, Any]) -> dict[str, Any]:
    address = search_item.get("address") if isinstance(search_item.get("address"), dict) else {}
    lat = coords.get("latitude")
    lng = coords.get("longitude")
    out: dict[str, Any] = {
        "latitude": float(lat) if lat not in (None, "") else None,
        "longitude": float(lng) if lng not in (None, "") else None,
        "city": address.get("city") or search_item.get("placeName"),
        "state": address.get("state"),
        "country": address.get("country") or "India",
        "pincode": address.get("pincode"),
        "geocoding_provider": "redcliffe",
    }
    return out


async def _call_with_optional_session_log(
    db: AsyncSession | None,
    *,
    engagement_id: int | None,
    user_id: int | None,
    api_url: str,
    request_payload: dict,
    call: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    if db is not None:
        try:
            result = await call()
        except RedcliffeApiError as exc:
            await log_redcliffe_call(
                db,
                engagement_id=engagement_id,
                user_id=user_id,
                api_url=api_url,
                request_payload=request_payload,
                response_payload=_sanitize(exc.body),
                status="failed",
                error_message=str(exc),
            )
            raise
        except Exception as exc:
            await log_redcliffe_call(
                db,
                engagement_id=engagement_id,
                user_id=user_id,
                api_url=api_url,
                request_payload=request_payload,
                status="failed",
                error_message=str(exc),
            )
            raise
        await log_redcliffe_call(
            db,
            engagement_id=engagement_id,
            user_id=user_id,
            api_url=api_url,
            request_payload=request_payload,
            response_payload=_sanitize(result),
            status="success",
        )
        return result
    return await _tracked_call(api_url=api_url, request_payload=request_payload, call=call)


async def resolve_coordinates_for_booking(
    db: AsyncSession | None,
    *,
    address_line: str | None,
    landmark: str | None,
    city: str | None,
    pincode: str | None,
    engagement_id: int | None = None,
    user_id: int | None = None,
    fallback_geocode: Callable[[], Awaitable[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Resolve lat/lng via Redcliffe search-area + eloc coordinates (partner-recommended path)."""
    place_query = build_redcliffe_place_query(
        address_line=address_line,
        landmark=landmark,
        city=city,
        pincode=pincode,
    )
    if not place_query:
        return {}

    search_url = redcliffe_client.search_area_api_url()
    search_req = {"place_query": place_query}
    try:
        search_data = await _call_with_optional_session_log(
            db,
            engagement_id=engagement_id,
            user_id=user_id,
            api_url=search_url,
            request_payload=search_req,
            call=lambda: redcliffe_client.search_area(place_query=place_query),
        )
    except (RedcliffeApiError, Exception):
        if fallback_geocode is None:
            return {}
        return await fallback_geocode()

    search_item = _first_search_result(search_data)
    if search_item is None:
        if fallback_geocode is None:
            return {}
        return await fallback_geocode()

    eloc = str(search_item.get("eloc") or "").strip()
    coords_url = redcliffe_client.coordinates_api_url()
    coords_req = {"eloc": eloc}
    try:
        coords = await _call_with_optional_session_log(
            db,
            engagement_id=engagement_id,
            user_id=user_id,
            api_url=coords_url,
            request_payload=coords_req,
            call=lambda: redcliffe_client.get_coordinates(eloc=eloc),
        )
    except (RedcliffeApiError, Exception):
        if fallback_geocode is None:
            return {}
        return await fallback_geocode()

    geocoded = _geocoded_from_redcliffe(search_item, coords)
    if geocoded.get("latitude") is None or geocoded.get("longitude") is None:
        if fallback_geocode is None:
            return {}
        return await fallback_geocode()
    pin_from_query = (pincode or "").strip()
    if pin_from_query and not geocoded.get("pincode"):
        geocoded["pincode"] = pin_from_query
    return geocoded


async def check_location_serviceable(*, latitude: float, longitude: float) -> dict[str, Any]:
    api_url = redcliffe_client.serviceability_api_url()
    req = {"latitude": latitude, "longitude": longitude}
    return await _tracked_call(
        api_url=api_url,
        request_payload=req,
        call=lambda: redcliffe_client.check_location_serviceable(
            latitude=latitude,
            longitude=longitude,
        ),
    )
