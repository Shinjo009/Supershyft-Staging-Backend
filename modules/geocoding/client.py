"""Nominatim + Google geocoding clients with provider fallback."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from core.config import settings
from modules.geocoding.enums import GeocodingProvider
from modules.geocoding.sync_log import (
    PROVIDER_GOOGLE_MAPS,
    PROVIDER_NOMINATIM,
    begin_geocode_sync_log,
    complete_geocode_sync_log,
    summarize_google_geocode_response,
    summarize_nominatim_geocode_response,
)

logger = logging.getLogger(__name__)

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
USER_AGENT = "SuperShyft"
DEFAULT_TIMEOUT_SECONDS = 8.0

LOCATION_FIELD_KEYS = (
    "address",
    "sub_locality",
    "landmark",
    "city",
    "pincode",
    "state",
    "country",
    "latitude",
    "longitude",
)


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def map_nominatim_result(item: dict[str, Any]) -> dict[str, Any]:
    """Map a Nominatim search result to engagement location fields."""
    address = item.get("address") if isinstance(item.get("address"), dict) else {}
    return {
        "display_name": _first_non_empty(item.get("display_name")),
        "address": _first_non_empty(item.get("display_name")),
        "sub_locality": _first_non_empty(address.get("suburb"), address.get("neighbourhood")),
        "landmark": _first_non_empty(item.get("name")),
        "city": _first_non_empty(
            address.get("city"),
            address.get("town"),
            address.get("village"),
        ),
        "pincode": _first_non_empty(address.get("postcode")),
        "state": _first_non_empty(address.get("state")),
        "country": _first_non_empty(address.get("country")),
        "latitude": _parse_float(item.get("lat")),
        "longitude": _parse_float(item.get("lon")),
    }


def _google_component(components: list[dict[str, Any]], *types: str) -> str | None:
    for component in components:
        if not isinstance(component, dict):
            continue
        component_types = component.get("types") or []
        if not isinstance(component_types, list):
            continue
        for wanted in types:
            if wanted in component_types:
                return _first_non_empty(component.get("long_name"), component.get("short_name"))
    return None


def _google_street_address_line(components: list[dict[str, Any]]) -> str | None:
    street_number = _google_component(components, "street_number")
    route = _google_component(components, "route")
    parts = [part for part in (street_number, route) if part]
    if parts:
        return " ".join(parts)
    return None


def map_google_result(item: dict[str, Any]) -> dict[str, Any]:
    """Map a Google Geocoding API result to engagement location fields."""
    components = item.get("address_components") if isinstance(item.get("address_components"), list) else []
    geometry = item.get("geometry") if isinstance(item.get("geometry"), dict) else {}
    location = geometry.get("location") if isinstance(geometry.get("location"), dict) else {}
    formatted = _first_non_empty(item.get("formatted_address"))
    address_line = _first_non_empty(_google_street_address_line(components), formatted)

    sub_locality = _google_component(
        components,
        "sublocality_level_1",
        "sublocality",
        "neighborhood",
        "sublocality_level_2",
        "sublocality_level_3",
    )
    landmark = _first_non_empty(
        _google_component(
            components,
            "premise",
            "point_of_interest",
            "establishment",
            "subpremise",
        ),
        _google_component(components, "neighborhood", "sublocality_level_1"),
    )

    return {
        "display_name": formatted,
        "address": address_line,
        "sub_locality": sub_locality,
        "landmark": landmark,
        "city": _google_component(
            components,
            "locality",
            "postal_town",
            "administrative_area_level_2",
        ),
        "pincode": _google_component(components, "postal_code"),
        "state": _google_component(components, "administrative_area_level_1"),
        "country": _google_component(components, "country"),
        "latitude": _parse_float(location.get("lat")),
        "longitude": _parse_float(location.get("lng")),
    }


async def search_nominatim(
    query: str,
    *,
    limit: int = 3,
    engagement_id: int | None = None,
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    """Search Nominatim and return mapped place suggestions.

    Never raises — returns an empty list on failure.
    """
    q = (query or "").strip()
    if not q:
        return []

    limit = max(1, min(int(limit), 10))
    request_payload = {
        "q": q,
        "format": "json",
        "addressdetails": 1,
        "limit": limit,
    }
    headers = {"User-Agent": USER_AGENT}

    sync_log_id = await begin_geocode_sync_log(
        provider=PROVIDER_NOMINATIM,
        api_url=NOMINATIM_SEARCH_URL,
        request_payload=request_payload,
        engagement_id=engagement_id,
        user_id=user_id,
    )

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            response = await client.get(NOMINATIM_SEARCH_URL, params=request_payload, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        await complete_geocode_sync_log(
            sync_log_id,
            status="failed",
            error_message=str(exc)[:2000] or "Nominatim search failed",
        )
        logger.warning("Nominatim search failed for query=%r", q, exc_info=True)
        return []

    if not isinstance(payload, list):
        await complete_geocode_sync_log(
            sync_log_id,
            status="failed",
            response_payload=summarize_nominatim_geocode_response(payload),
            error_message="Nominatim response was not a list",
        )
        return []

    results: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        results.append(map_nominatim_result(item))

    await complete_geocode_sync_log(
        sync_log_id,
        status="success",
        response_payload={
            **summarize_nominatim_geocode_response(payload),
            "mapped_results_count": len(results),
        },
    )
    return results


async def search_google(
    query: str,
    *,
    limit: int = 3,
    engagement_id: int | None = None,
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    """Search Google Geocoding API and return mapped place suggestions.

    Never raises — returns an empty list on failure or missing API key.
    """
    q = (query or "").strip()
    if not q:
        return []

    limit = max(1, min(int(limit), 10))
    request_payload = {"address": q, "limit": limit}

    api_key = (settings.GOOGLE_MAPS_API_KEY or "").strip()
    if not api_key:
        sync_log_id = await begin_geocode_sync_log(
            provider=PROVIDER_GOOGLE_MAPS,
            api_url=GOOGLE_GEOCODE_URL,
            request_payload=request_payload,
            engagement_id=engagement_id,
            user_id=user_id,
        )
        await complete_geocode_sync_log(
            sync_log_id,
            status="failed",
            error_message="GOOGLE_MAPS_API_KEY is not configured",
        )
        logger.warning("Google geocode skipped: GOOGLE_MAPS_API_KEY is not configured")
        return []

    sync_log_id = await begin_geocode_sync_log(
        provider=PROVIDER_GOOGLE_MAPS,
        api_url=GOOGLE_GEOCODE_URL,
        request_payload=request_payload,
        engagement_id=engagement_id,
        user_id=user_id,
    )

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            response = await client.get(
                GOOGLE_GEOCODE_URL,
                params={"address": q, "key": api_key},
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        await complete_geocode_sync_log(
            sync_log_id,
            status="failed",
            error_message=str(exc)[:2000] or "Google geocode search failed",
        )
        logger.warning("Google geocode search failed for query=%r", q, exc_info=True)
        return []

    if not isinstance(payload, dict):
        await complete_geocode_sync_log(
            sync_log_id,
            status="failed",
            error_message="Google geocode response was not an object",
        )
        return []

    status = str(payload.get("status") or "").upper()
    if status == "ZERO_RESULTS":
        await complete_geocode_sync_log(
            sync_log_id,
            status="success",
            response_payload=summarize_google_geocode_response(payload),
        )
        return []
    if status != "OK":
        error_message = str(payload.get("error_message") or f"Google geocode status={status}")
        await complete_geocode_sync_log(
            sync_log_id,
            status="failed",
            response_payload=summarize_google_geocode_response(payload),
            error_message=error_message[:2000],
        )
        logger.warning(
            "Google geocode non-OK status=%s for query=%r error_message=%r",
            status,
            q,
            payload.get("error_message"),
        )
        return []

    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        await complete_geocode_sync_log(
            sync_log_id,
            status="failed",
            response_payload=summarize_google_geocode_response(payload),
            error_message="Google geocode results missing or invalid",
        )
        return []

    results: list[dict[str, Any]] = []
    for item in raw_results[:limit]:
        if not isinstance(item, dict):
            continue
        results.append(map_google_result(item))

    await complete_geocode_sync_log(
        sync_log_id,
        status="success",
        response_payload={
            **summarize_google_geocode_response(payload),
            "mapped_results_count": len(results),
        },
    )
    return results


async def _search_provider(
    provider: GeocodingProvider,
    query: str,
    *,
    limit: int,
    engagement_id: int | None = None,
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    if provider == GeocodingProvider.google:
        return await search_google(
            query,
            limit=limit,
            engagement_id=engagement_id,
            user_id=user_id,
        )
    return await search_nominatim(
        query,
        limit=limit,
        engagement_id=engagement_id,
        user_id=user_id,
    )


def _other_provider(primary: GeocodingProvider) -> GeocodingProvider:
    if primary == GeocodingProvider.google:
        return GeocodingProvider.nominatim
    return GeocodingProvider.google


async def search_places_with_fallback(
    query: str,
    *,
    limit: int = 3,
    primary: GeocodingProvider = GeocodingProvider.google,
    engagement_id: int | None = None,
    user_id: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Try primary provider, then the other on empty/error. Returns (results, meta)."""
    primary_provider = primary if isinstance(primary, GeocodingProvider) else GeocodingProvider(primary)
    secondary = _other_provider(primary_provider)

    primary_results = await _search_provider(
        primary_provider,
        query,
        limit=limit,
        engagement_id=engagement_id,
        user_id=user_id,
    )
    if primary_results:
        return primary_results, {
            "geocoding_provider": primary_provider.value,
            "geocoding_fallback_used": False,
        }

    secondary_results = await _search_provider(
        secondary,
        query,
        limit=limit,
        engagement_id=engagement_id,
        user_id=user_id,
    )
    if secondary_results:
        return secondary_results, {
            "geocoding_provider": secondary.value,
            "geocoding_fallback_used": True,
        }

    return [], {
        "geocoding_provider": primary_provider.value,
        "geocoding_fallback_used": True,
    }


async def search_places(
    query: str,
    *,
    limit: int = 3,
    primary: GeocodingProvider = GeocodingProvider.google,
    engagement_id: int | None = None,
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    """Search places with provider fallback. Returns mapped suggestions only."""
    results, _meta = await search_places_with_fallback(
        query,
        limit=limit,
        primary=primary,
        engagement_id=engagement_id,
        user_id=user_id,
    )
    return results


def build_booking_geocode_queries(
    *,
    address_line: str | None = None,
    landmark: str | None = None,
    city: str | None = None,
    pincode: str | None = None,
) -> tuple[str, str]:
    """Return (google_query, nominatim_query) for B2C/booking geocoding."""
    city_s = (city or "").strip()
    pincode_s = (pincode or "").strip()
    nominatim_query = f"{city_s} {pincode_s}".strip()

    google_parts = [
        (address_line or "").strip(),
        (landmark or "").strip(),
        city_s,
        pincode_s,
    ]
    google_query = ", ".join(part for part in google_parts if part)

    return google_query, nominatim_query


async def search_places_for_booking(
    *,
    address_line: str | None = None,
    landmark: str | None = None,
    city: str | None = None,
    pincode: str | None = None,
    primary: GeocodingProvider = GeocodingProvider.google,
    limit: int = 1,
    engagement_id: int | None = None,
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    """Geocode for booking: Google uses full address; Nominatim uses city+pincode only.

    On provider fallback, the secondary provider uses its own query shape (not the primary's).
    """
    google_query, nominatim_query = build_booking_geocode_queries(
        address_line=address_line,
        landmark=landmark,
        city=city,
        pincode=pincode,
    )
    primary_provider = primary if isinstance(primary, GeocodingProvider) else GeocodingProvider(primary)
    secondary = _other_provider(primary_provider)

    if primary_provider == GeocodingProvider.google:
        primary_query, secondary_query = google_query, nominatim_query
    else:
        primary_query, secondary_query = nominatim_query, google_query

    if primary_query:
        primary_results = await _search_provider(
            primary_provider,
            primary_query,
            limit=limit,
            engagement_id=engagement_id,
            user_id=user_id,
        )
        if primary_results:
            return primary_results

    if secondary_query:
        return await _search_provider(
            secondary,
            secondary_query,
            limit=limit,
            engagement_id=engagement_id,
            user_id=user_id,
        )

    return []


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def location_fields_complete(
    *,
    address: str | None = None,
    sub_locality: str | None = None,
    landmark: str | None = None,
    city: str | None = None,
    pincode: str | None = None,
    state: str | None = None,
    country: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> bool:
    return all(
        _is_present(value)
        for value in (
            address,
            sub_locality,
            landmark,
            city,
            pincode,
            state,
            country,
            latitude,
            longitude,
        )
    )


def merge_location_fields(
    existing: dict[str, Any],
    geocoded: dict[str, Any],
) -> dict[str, Any]:
    """Fill only missing location fields from geocoded data."""
    merged = dict(existing)
    for key in LOCATION_FIELD_KEYS:
        if not _is_present(merged.get(key)) and _is_present(geocoded.get(key)):
            merged[key] = geocoded[key]
    return merged


async def enrich_location_fields(
    *,
    address: str | None = None,
    sub_locality: str | None = None,
    landmark: str | None = None,
    city: str | None = None,
    pincode: str | None = None,
    state: str | None = None,
    country: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    primary: GeocodingProvider = GeocodingProvider.google,
    engagement_id: int | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Return location fields, geocoding missing ones from address when needed."""
    fields = {
        "address": (address or "").strip() or None,
        "sub_locality": (sub_locality or "").strip() or None if isinstance(sub_locality, str) else sub_locality,
        "landmark": (landmark or "").strip() or None if isinstance(landmark, str) else landmark,
        "city": (city or "").strip() or None if isinstance(city, str) else city,
        "pincode": (pincode or "").strip() or None if isinstance(pincode, str) else pincode,
        "state": (state or "").strip() or None if isinstance(state, str) else state,
        "country": (country or "").strip() or None if isinstance(country, str) else country,
        "latitude": _parse_float(latitude),
        "longitude": _parse_float(longitude),
    }

    if location_fields_complete(**fields):
        return fields

    query_parts = [
        fields["address"],
        fields["sub_locality"],
        fields["landmark"],
        fields["city"],
        fields["pincode"],
        fields["state"],
        fields["country"],
    ]
    query = ", ".join(part for part in query_parts if part)
    if not query:
        return fields

    results = await search_places(
        query,
        limit=1,
        primary=primary,
        engagement_id=engagement_id,
        user_id=user_id,
    )
    if not results:
        return fields

    # Prefer keeping the caller-provided address string over display_name.
    geocoded = dict(results[0])
    if fields["address"]:
        geocoded["address"] = fields["address"]

    return merge_location_fields(fields, geocoded)
