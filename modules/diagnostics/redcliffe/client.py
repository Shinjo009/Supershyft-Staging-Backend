"""Redcliffe Labs Partner API HTTP client."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class RedcliffeApiError(Exception):
    """Redcliffe API returned an error response."""

    def __init__(self, message: str, *, status_code: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _base_url() -> str:
    return (settings.REDCLIFFE_BASE_URL or "").strip().rstrip("/")


def _timeout() -> float:
    return float(settings.REDCLIFFE_TIMEOUT_SECONDS or 15)


def _headers() -> dict[str, str]:
    return {"key": settings.REDCLIFFE_API_KEY or ""}


def search_area_api_url() -> str:
    return f"{_base_url()}/api/partner/v2/get-partner-location-2-eloc/"


def coordinates_api_url() -> str:
    return f"{_base_url()}/api/partner/v2/get-partner-loc-2-eloc/"


def serviceability_api_url() -> str:
    return f"{_base_url()}/api/center/v2/is-location-serviceable/"


def time_slot_list_api_url() -> str:
    return f"{_base_url()}/api/booking/v2/get-time-slot-list/"


def center_create_booking_api_url() -> str:
    return f"{_base_url()}/api/external/v2/center-create-booking/"


def center_confirm_booking_api_url() -> str:
    return f"{_base_url()}/api/external/v2/center-confirm-booking/"


def _coord(value: float) -> float:
    return round(float(value), 6)


def _failure_message(data: Any, fallback: str) -> str:
    if isinstance(data, dict):
        msg = data.get("message")
        if isinstance(msg, str) and msg.strip():
            return msg.strip()
        status = data.get("status")
        if isinstance(status, str) and status.strip():
            return status.strip()
    return fallback


async def search_area(*, place_query: str) -> dict[str, Any]:
    """GET area search → eloc suggestions."""
    url = search_area_api_url()
    params = {"place_query": place_query.strip()}
    async with httpx.AsyncClient(timeout=_timeout()) as client:
        resp = await client.get(url, params=params, headers=_headers())
    if resp.status_code == 401:
        raise RedcliffeApiError("Unauthorized", status_code=401, body=resp.text)
    try:
        data = resp.json()
    except Exception:
        resp.raise_for_status()
        raise RedcliffeApiError("Invalid JSON response", status_code=resp.status_code, body=resp.text)
    if resp.status_code >= 400:
        raise RedcliffeApiError(
            _failure_message(data, "Area search failed"),
            status_code=resp.status_code,
            body=data,
        )
    if isinstance(data, dict) and str(data.get("status", "")).lower() == "failure":
        raise RedcliffeApiError(
            _failure_message(data, "No record(s) found"),
            status_code=404,
            body=data,
        )
    return data if isinstance(data, dict) else {"data": data}


async def get_coordinates(*, eloc: str) -> dict[str, Any]:
    """GET eloc → latitude/longitude."""
    url = coordinates_api_url()
    params = {"eloc": eloc.strip()}
    async with httpx.AsyncClient(timeout=_timeout()) as client:
        resp = await client.get(url, params=params, headers=_headers())
    if resp.status_code == 401:
        raise RedcliffeApiError("Unauthorized", status_code=401, body=resp.text)
    try:
        data = resp.json()
    except Exception:
        resp.raise_for_status()
        raise RedcliffeApiError("Invalid JSON response", status_code=resp.status_code, body=resp.text)
    if resp.status_code >= 400:
        raise RedcliffeApiError(
            _failure_message(data, "Coordinate lookup failed"),
            status_code=resp.status_code,
            body=data,
        )
    if isinstance(data, dict) and str(data.get("status", "")).lower() == "failure":
        raise RedcliffeApiError(
            _failure_message(data, "eloc is not valid"),
            status_code=422,
            body=data,
        )
    lat = data.get("latitude") if isinstance(data, dict) else None
    lng = data.get("longitude") if isinstance(data, dict) else None
    if lat in ("", None) or lng in ("", None):
        raise RedcliffeApiError("Invalid eloc coordinates", status_code=422, body=data)
    return data


async def check_location_serviceable(*, latitude: float, longitude: float) -> dict[str, Any]:
    """GET lat/lng serviceability."""
    url = serviceability_api_url()
    params = {
        "latitude": str(_coord(latitude)),
        "longitude": str(_coord(longitude)),
    }
    async with httpx.AsyncClient(timeout=_timeout()) as client:
        resp = await client.get(url, params=params, headers=_headers())
    if resp.status_code == 401:
        raise RedcliffeApiError("Unauthorized", status_code=401, body=resp.text)
    try:
        data = resp.json()
    except Exception:
        resp.raise_for_status()
        raise RedcliffeApiError("Invalid JSON response", status_code=resp.status_code, body=resp.text)
    if resp.status_code >= 400:
        raise RedcliffeApiError(
            _failure_message(data, "Serviceability check failed"),
            status_code=resp.status_code,
            body=data,
        )
    return data if isinstance(data, dict) else {"data": data}


def is_serviceable_response(body: dict[str, Any]) -> bool:
    return str(body.get("status", "")).lower() == "success"


def is_api_success(body: dict[str, Any]) -> bool:
    status = str(body.get("status", "")).strip().lower()
    return status in ("success", "sucess")


async def _request_json(
    *,
    method: str,
    url: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=_timeout()) as client:
        if method.upper() == "GET":
            resp = await client.get(url, params=params, headers=_headers())
        else:
            resp = await client.post(url, json=json_body, headers=_headers())
    if resp.status_code == 401:
        raise RedcliffeApiError("Unauthorized", status_code=401, body=resp.text)
    try:
        data = resp.json()
    except Exception:
        resp.raise_for_status()
        raise RedcliffeApiError("Invalid JSON response", status_code=resp.status_code, body=resp.text)
    if not isinstance(data, dict):
        data = {"data": data}
    if resp.status_code >= 400:
        raise RedcliffeApiError(
            _failure_message(data, f"Redcliffe API HTTP {resp.status_code}"),
            status_code=resp.status_code,
            body=data,
        )
    return data


async def get_time_slot_list(
    *,
    collection_date: str,
    latitude: float,
    longitude: float,
    customer_gender: str | None = None,
) -> dict[str, Any]:
    """GET collection slots for lat/lng on a collection date."""
    url = time_slot_list_api_url()
    params: dict[str, Any] = {
        "collection_date": collection_date,
        "latitude": str(_coord(latitude)),
        "longitude": str(_coord(longitude)),
    }
    if customer_gender:
        params["customer_gender"] = customer_gender
    data = await _request_json(method="GET", url=url, params=params)
    if not is_api_success(data) and str(data.get("status", "")).strip().lower() == "failure":
        raise RedcliffeApiError(
            _failure_message(data, "Failed to fetch slots"),
            status_code=422,
            body=data,
        )
    return data


async def center_create_booking(payload: dict[str, Any]) -> dict[str, Any]:
    """POST temporary home-collection booking (slot held ~30 minutes)."""
    url = center_create_booking_api_url()
    data = await _request_json(method="POST", url=url, json_body=payload)
    if not is_api_success(data):
        raise RedcliffeApiError(
            _failure_message(data, "Redcliffe booking creation failed"),
            status_code=422,
            body=data,
        )
    return data


async def center_confirm_booking(*, booking_id: int | str, is_confirmed: bool = True) -> dict[str, Any]:
    """POST finalize temporary booking after payment at partner."""
    url = center_confirm_booking_api_url()
    payload = {"booking_id": booking_id, "is_confirmed": is_confirmed}
    data = await _request_json(method="POST", url=url, json_body=payload)
    if not is_api_success(data):
        raise RedcliffeApiError(
            _failure_message(data, "Redcliffe booking confirmation failed"),
            status_code=422,
            body=data,
        )
    return data
