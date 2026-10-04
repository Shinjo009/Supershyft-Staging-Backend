"""HTTP client for Orange Health Partner API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class OrangeHealthApiError(Exception):
    """Orange Health API returned an error response."""

    def __init__(self, message: str, *, status_code: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _base_url() -> str:
    """Normalize base URL (docs allow host with or without trailing /v1)."""
    raw = (settings.ORANGE_HEALTH_BASE_URL or "").strip().rstrip("/")
    if raw.endswith("/v1"):
        raw = raw[: -len("/v1")]
    return raw


def serviceability_api_url() -> str:
    return f"{_base_url()}/v1/partner/serviceability"


def order_api_url() -> str:
    return f"{_base_url()}/v1/partner/order"


def _coord(value: float) -> float:
    """Partner docs recommend >= 4 decimal places for serviceability."""
    return round(float(value), 6)


def _format_api_error(data: Any, fallback: str) -> str:
    if isinstance(data, dict):
        status = data.get("status")
        if isinstance(status, str) and status.strip():
            return status.strip()
        err = data.get("error")
        if isinstance(err, dict):
            parts = [str(v) for v in err.values() if v]
            if parts:
                return "; ".join(parts)
        if isinstance(err, str) and err.strip():
            return err.strip()
    return fallback


def _headers() -> dict[str, str]:
    return {"api_key": settings.ORANGE_HEALTH_API_KEY or ""}


async def check_serviceability(
    *,
    latitude: float,
    longitude: float,
    request_date: str,
) -> dict[str, Any]:
    """GET /v1/partner/serviceability."""
    url = serviceability_api_url()
    params = {
        "latitude": _coord(latitude),
        "longitude": _coord(longitude),
        "request_date": request_date,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params, headers=_headers())
    if resp.status_code == 401:
        raise OrangeHealthApiError("Unauthorized", status_code=401, body=resp.text)
    if resp.status_code == 404:
        try:
            data = resp.json()
        except Exception:
            data = {"status": resp.text}
        raise OrangeHealthApiError(
            _format_api_error(data, "Location is not serviceable"),
            status_code=404,
            body=data,
        )
    if resp.status_code == 400:
        try:
            data = resp.json()
        except Exception:
            data = {"status": resp.text}
        raise OrangeHealthApiError(
            _format_api_error(data, "Bad request"),
            status_code=400,
            body=data,
        )
    resp.raise_for_status()
    return resp.json()


async def create_order(payload: dict[str, Any]) -> dict[str, Any]:
    """POST /v1/partner/order."""
    url = order_api_url()
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            url,
            json=payload,
            headers={**_headers(), "Content-Type": "application/json"},
        )
    if resp.status_code == 401:
        raise OrangeHealthApiError("Unauthorized", status_code=401, body=resp.text)
    if resp.status_code in (400, 425):
        try:
            data = resp.json()
        except Exception:
            data = {"status": resp.text}
        raise OrangeHealthApiError(
            _format_api_error(data, "Order request failed"),
            status_code=resp.status_code,
            body=data,
        )
    resp.raise_for_status()
    return resp.json()
