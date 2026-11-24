"""Structured request payload for Orange Health integration sync logs."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


def orange_http_method_for_url(api_url: str) -> str:
    path = (urlparse(api_url).path or "").lower()
    if path.endswith("/reschedule") or path.endswith("/cancel"):
        return "PATCH"
    if path.endswith("/order"):
        return "POST"
    if "serviceability" in path:
        return "GET"
    return "POST"


def orange_api_name_from_url(api_url: str) -> str:
    path = (urlparse(api_url).path or "").strip("/")
    if not path:
        return api_url
    segments = path.split("/")
    return segments[-1] if segments else api_url


def build_orange_health_sync_request_payload(
    *,
    api_url: str,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    http_method: str | None = None,
) -> dict[str, Any]:
    """Envelope stored in integration_sync_logs.request_payload (admin detail panel)."""
    method = (http_method or orange_http_method_for_url(api_url)).upper()
    payload: dict[str, Any] = {
        "http_method": method,
        "url": api_url,
        "api_name": orange_api_name_from_url(api_url),
    }
    if query:
        payload["query"] = query
    if body is not None:
        payload["body"] = body
    return payload


def normalize_orange_health_request_payload(
    api_url: str,
    request_payload: dict[str, Any] | None,
    *,
    query: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if request_payload is None and query is None:
        return None
    if isinstance(request_payload, dict) and request_payload.get("http_method"):
        out = dict(request_payload)
        if query and "query" not in out:
            out["query"] = query
        if "url" not in out:
            out["url"] = api_url
        return out
    return build_orange_health_sync_request_payload(
        api_url=api_url,
        body=request_payload,
        query=query,
    )