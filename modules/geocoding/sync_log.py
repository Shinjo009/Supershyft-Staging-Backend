"""Integration sync logging for Google Maps and Nominatim geocoding calls."""

from __future__ import annotations

import json
from typing import Any

from modules.audit.cron_sync_logging import (
    finalize_integration_sync_log_isolated,
    persist_integration_sync_log_isolated,
    sanitize_response_payload,
)

PROVIDER_GOOGLE_MAPS = "google_maps"
PROVIDER_NOMINATIM = "nominatim"

_MAX_RESPONSE_JSON_BYTES = 50_000


def _truncate_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    try:
        encoded = json.dumps(payload, default=str)
    except (TypeError, ValueError):
        return {"summary": "response_not_serializable"}
    if len(encoded) <= _MAX_RESPONSE_JSON_BYTES:
        return payload
    return {
        "truncated": True,
        "original_bytes": len(encoded),
        **{k: payload[k] for k in list(payload.keys())[:8]},
    }


def summarize_google_geocode_response(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"status": "invalid_response"}
    status = str(payload.get("status") or "").upper()
    raw_results = payload.get("results")
    results_count = len(raw_results) if isinstance(raw_results, list) else 0
    summary: dict[str, Any] = {
        "status": status,
        "results_count": results_count,
    }
    if results_count and isinstance(raw_results, list) and isinstance(raw_results[0], dict):
        first = raw_results[0]
        summary["first_formatted_address"] = first.get("formatted_address")
        geometry = first.get("geometry") if isinstance(first.get("geometry"), dict) else {}
        location = geometry.get("location") if isinstance(geometry.get("location"), dict) else {}
        if location:
            summary["first_location"] = {
                "lat": location.get("lat"),
                "lng": location.get("lng"),
            }
    error_message = payload.get("error_message")
    if error_message:
        summary["error_message"] = error_message
    return _truncate_payload(summary) or summary


def summarize_nominatim_geocode_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list):
        return {"results_count": 0, "invalid_response": True}
    summary: dict[str, Any] = {"results_count": len(payload)}
    if payload and isinstance(payload[0], dict):
        first = payload[0]
        summary["first_display_name"] = first.get("display_name")
        summary["first_lat"] = first.get("lat")
        summary["first_lon"] = first.get("lon")
    return _truncate_payload(summary) or summary


async def begin_geocode_sync_log(
    *,
    provider: str,
    api_url: str,
    request_payload: dict[str, Any] | None,
    engagement_id: int | None = None,
    user_id: int | None = None,
) -> int:
    return await persist_integration_sync_log_isolated(
        provider=provider,
        api_url=api_url,
        engagement_id=engagement_id,
        user_id=user_id,
        request_payload=request_payload,
        status="pending",
    )


async def complete_geocode_sync_log(
    sync_log_id: int,
    *,
    status: str,
    response_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    await finalize_integration_sync_log_isolated(
        sync_log_id=sync_log_id,
        status=status,
        response_payload=sanitize_response_payload(response_payload),
        error_message=error_message,
    )
