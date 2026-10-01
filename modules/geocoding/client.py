"""Nominatim + Google geocoding clients with provider fallback."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from core.config import settings
from modules.geocoding.enums import GeocodingProvider

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


def map_google_result(item: dict[str, Any]) -> dict[str, Any]:
    """Map a Google Geocoding API result to engagement location fields."""
    components = item.get("address_components") if isinstance(item.get("address_components"), list) else []
    geometry = item.get("geometry") if isinstance(item.get("geometry"), dict) else {}
    location = geometry.get("location") if isinstance(geometry.get("location"), dict) else {}
    formatted = _first_non_empty(item.get("formatted_address"))

    return {
        "display_name": formatted,
        "address": formatted,
        "sub_locality": _google_component(
            components,
            "sublocality_level_1",
            "sublocality",
            "neighborhood",
        ),
        "landmark": _google_component(components, "premise", "point_of_interest", "establishment"),
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


async def search_nominatim(query: str, *, limit: int = 3) -> list[dict[str, Any]]:
    """Search Nominatim and return mapped place suggestions.

    Never raises — returns an empty list on failure.
    """
    q = (query or "").strip()
    if not q:
        return []

    limit = max(1, min(int(limit), 10))
    params = {
        "q": q,
        "format": "json",
        "addressdetails": 1,
        "limit": limit,
    }
    headers = {"User-Agent": USER_AGENT}

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            response = await client.get(NOMINATIM_SEARCH_URL, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except Exception:
        logger.warning("Nominatim search failed for query=%r", q, exc_info=True)
        return []

    if not isinstance(payload, list):
        return []

    results: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        results.append(map_nominatim_result(item))
    return results


async def search_google(query: str, *, limit: int = 3) -> list[dict[str, Any]]:
    """Search Google Geocoding API and return mapped place suggestions.

    Never raises — returns an empty list on failure or missing API key.
    """
    q = (query or "").strip()
    if not q:
        return []

    api_key = (settings.GOOGLE_MAPS_API_KEY or "").strip()
    if not api_key:
        logger.warning("Google geocode skipped: GOOGLE_MAPS_API_KEY is not configured")
        return []

    limit = max(1, min(int(limit), 10))
    params = {
        "address": q,
        "key": api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            response = await client.get(GOOGLE_GEOCODE_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception:
        logger.warning("Google geocode search failed for query=%r", q, exc_info=True)
        return []

    if not isinstance(payload, dict):
        return []

    status = str(payload.get("status") or "").upper()
    if status == "ZERO_RESULTS":
        return []
    if status != "OK":
        logger.warning(
            "Google geocode non-OK status=%s for query=%r error_message=%r",
            status,
            q,
            payload.get("error_message"),
        )
        return []

    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        return []

    results: list[dict[str, Any]] = []
    for item in raw_results[:limit]:
        if not isinstance(item, dict):
            continue
        results.append(map_google_result(item))
    return results


async def _search_provider(
    provider: GeocodingProvider,
    query: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    if provider == GeocodingProvider.google:
        return await search_google(query, limit=limit)
    return await search_nominatim(query, limit=limit)


def _other_provider(primary: GeocodingProvider) -> GeocodingProvider:
    if primary == GeocodingProvider.google:
        return GeocodingProvider.nominatim
    return GeocodingProvider.google


async def search_places_with_fallback(
    query: str,
    *,
    limit: int = 3,
    primary: GeocodingProvider = GeocodingProvider.google,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Try primary provider, then the other on empty/error. Returns (results, meta)."""
    primary_provider = primary if isinstance(primary, GeocodingProvider) else GeocodingProvider(primary)
    secondary = _other_provider(primary_provider)

    primary_results = await _search_provider(primary_provider, query, limit=limit)
    if primary_results:
        return primary_results, {
            "geocoding_provider": primary_provider.value,
            "geocoding_fallback_used": False,
        }

    secondary_results = await _search_provider(secondary, query, limit=limit)
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
) -> list[dict[str, Any]]:
    """Search places with provider fallback. Returns mapped suggestions only."""
    results, _meta = await search_places_with_fallback(query, limit=limit, primary=primary)
    return results


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

    results = await search_places(query, limit=1, primary=primary)
    if not results:
        return fields

    # Prefer keeping the caller-provided address string over display_name.
    geocoded = dict(results[0])
    if fields["address"]:
        geocoded["address"] = fields["address"]

    return merge_location_fields(fields, geocoded)
