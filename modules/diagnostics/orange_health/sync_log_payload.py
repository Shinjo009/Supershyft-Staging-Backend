"""Structured request payload for Orange Health integration sync logs."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from modules.diagnostics.orange_health.cancel_helpers import ORANGE_CANCEL_PARTNER_KEYS
from modules.diagnostics.orange_health.reschedule_helpers import ORANGE_RESCHEDULE_PARTNER_KEYS


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


def _partner_body_keys_for_payload(payload: dict[str, Any]) -> frozenset[str]:
    api_name = (payload.get("api_name") or "").strip().lower()
    if api_name == "cancel":
        return ORANGE_CANCEL_PARTNER_KEYS
    return ORANGE_RESCHEDULE_PARTNER_KEYS


def extract_partner_body_from_log(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Partner JSON body only — supports envelope or legacy flat rows."""
    if not isinstance(payload, dict):
        return {}
    keys = _partner_body_keys_for_payload(payload)
    nested = payload.get("body")
    if isinstance(nested, dict):
        return {k: nested[k] for k in keys if k in nested}
    return {k: payload[k] for k in keys if k in payload}


def extract_internal_from_log(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    internal = payload.get("internal")
    if isinstance(internal, dict):
        return internal
    audit = payload.get("audit")
    if isinstance(audit, dict):
        return audit
    return None


def build_orange_health_sync_request_payload(
    *,
    api_url: str,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    http_method: str | None = None,
    path: dict[str, Any] | None = None,
    internal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Envelope stored in integration_sync_logs.request_payload (admin detail panel)."""
    method = (http_method or orange_http_method_for_url(api_url)).upper()
    payload: dict[str, Any] = {
        "http_method": method,
        "url": api_url,
        "api_name": orange_api_name_from_url(api_url),
    }
    if path:
        payload["path"] = path
    if query:
        payload["query"] = query
    if body is not None:
        payload["body"] = body
    if internal:
        payload["internal"] = internal
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