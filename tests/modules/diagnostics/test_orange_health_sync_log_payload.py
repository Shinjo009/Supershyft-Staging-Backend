"""Tests for Orange Health integration sync log payload envelope."""

from __future__ import annotations

from modules.diagnostics.orange_health.sync_log_payload import (
    build_orange_health_sync_request_payload,
    normalize_orange_health_request_payload,
    orange_http_method_for_url,
)


def test_orange_http_method_for_reschedule_is_patch():
    assert (
        orange_http_method_for_url(
            "https://partner-api.orangehealth.in/v1/partner/MUM6477853/reschedule"
        )
        == "PATCH"
    )


def test_build_payload_includes_method_url_and_body():
    url = "https://partner-api.orangehealth.in/v1/partner/MUM1/reschedule"
    body = {"requested_slot_time": "2026-11-27T09:00:00", "reschedule_reason": "x"}
    payload = build_orange_health_sync_request_payload(
        api_url=url,
        body=body,
        query={"token": "[redacted]"},
    )
    assert payload["http_method"] == "PATCH"
    assert payload["url"] == url
    assert payload["api_name"] == "reschedule"
    assert payload["body"] == body
    assert payload["query"] == {"token": "[redacted]"}


def test_normalize_wraps_legacy_body_only_payload():
    url = "https://example.test/v1/partner/serviceability"
    legacy = {"latitude": 12.9, "longitude": 77.6}
    out = normalize_orange_health_request_payload(url, legacy)
    assert out is not None
    assert out["http_method"] == "GET"
    assert out["body"] == legacy