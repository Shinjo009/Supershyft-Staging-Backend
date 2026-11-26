"""Tests for Orange Health HTTP client error mapping."""

from __future__ import annotations

import pytest

from modules.diagnostics.orange_health.client import (
    OrangeHealthApiError,
    cancel_api_url,
    cancel_order,
    check_serviceability,
    reschedule_order,
    reschedule_api_url,
)


@pytest.mark.asyncio
async def test_check_serviceability_not_serviceable(monkeypatch):
    class FakeResponse:
        status_code = 404

        def json(self):
            return {"status": "Location is not serviceable"}

    class FakeClient:
        async def get(self, *args, **kwargs):
            return FakeResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.httpx.AsyncClient",
        lambda **kwargs: FakeClient(),
    )
    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.settings.ORANGE_HEALTH_BASE_URL",
        "https://example.test",
    )
    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.settings.ORANGE_HEALTH_API_KEY",
        "key",
    )

    with pytest.raises(OrangeHealthApiError) as exc:
        await check_serviceability(latitude=12.94, longitude=77.62, request_date="2026-02-28")
    assert exc.value.status_code == 404


def test_reschedule_api_url(monkeypatch):
    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.settings.ORANGE_HEALTH_BASE_URL",
        "https://sandbox-partner-api.orangehealth.dev/v1",
    )
    assert reschedule_api_url("BLR5394531") == (
        "https://sandbox-partner-api.orangehealth.dev/v1/partner/BLR5394531/reschedule"
    )


@pytest.mark.asyncio
async def test_reschedule_order_success(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"result": "ok"}

        def raise_for_status(self):
            return None

    class FakeClient:
        async def patch(self, url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return FakeResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.httpx.AsyncClient",
        lambda **kwargs: FakeClient(),
    )
    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.settings.ORANGE_HEALTH_API_KEY",
        "key",
    )
    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.settings.ORANGE_HEALTH_BASE_URL",
        "https://example.test",
    )

    resp = await reschedule_order(
        request_id="BLR1",
        token="tok",
        payload={
            "requested_slot_time": "2026-06-19T06:00:00",
            "reschedule_reason": "Reason",
            "reschedule_explanation": "Reason",
        },
    )
    assert resp == {"result": "ok"}
    assert captured["kwargs"]["params"] == {"token": "tok"}
    assert "audit" not in captured["kwargs"]["json"]


@pytest.mark.asyncio
async def test_reschedule_order_strips_extra_body_keys(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"result": "ok"}

        def raise_for_status(self):
            return None

    class FakeClient:
        async def patch(self, url, **kwargs):
            captured["json"] = kwargs.get("json")
            return FakeResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.httpx.AsyncClient",
        lambda **kwargs: FakeClient(),
    )
    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.settings.ORANGE_HEALTH_API_KEY",
        "key",
    )
    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.settings.ORANGE_HEALTH_BASE_URL",
        "https://example.test",
    )

    await reschedule_order(
        request_id="BLR1",
        token="tok",
        payload={
            "requested_slot_time": "2026-06-19T06:00:00",
            "reschedule_reason": "Reason",
            "reschedule_explanation": "Reason",
            "audit": {"operation": "reschedule"},
        },
    )
    assert "audit" not in captured["json"]
    assert set(captured["json"].keys()) == {
        "requested_slot_time",
        "reschedule_reason",
        "reschedule_explanation",
    }


@pytest.mark.asyncio
async def test_reschedule_order_maps_400_status(monkeypatch):
    class FakeResponse:
        status_code = 400

        def json(self):
            return {"status": "Requested slot is not available"}

    class FakeClient:
        async def patch(self, *args, **kwargs):
            return FakeResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.httpx.AsyncClient",
        lambda **kwargs: FakeClient(),
    )
    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.settings.ORANGE_HEALTH_API_KEY",
        "key",
    )
    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.settings.ORANGE_HEALTH_BASE_URL",
        "https://example.test",
    )

    with pytest.raises(OrangeHealthApiError) as exc:
        await reschedule_order(
            request_id="BLR1",
            token="tok",
            payload={
                "requested_slot_time": "2026-06-19T06:00:00",
                "reschedule_reason": "r",
                "reschedule_explanation": "e",
            },
        )
    assert exc.value.status_code == 400
    assert "not available" in str(exc.value).lower()


def test_cancel_api_url(monkeypatch):
    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.settings.ORANGE_HEALTH_BASE_URL",
        "https://sandbox-partner-api.orangehealth.dev/v1",
    )
    assert cancel_api_url("BLR5394531") == (
        "https://sandbox-partner-api.orangehealth.dev/v1/partner/BLR5394531/cancel"
    )


@pytest.mark.asyncio
async def test_cancel_order_success(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "status": {
                    "status": "Cancellation Request with ID : BLR343435 is in process",
                }
            }

        def raise_for_status(self):
            return None

    class FakeClient:
        async def patch(self, url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return FakeResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.httpx.AsyncClient",
        lambda **kwargs: FakeClient(),
    )
    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.settings.ORANGE_HEALTH_API_KEY",
        "key",
    )
    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.settings.ORANGE_HEALTH_BASE_URL",
        "https://example.test",
    )

    resp = await cancel_order(
        request_id="BLR1",
        token="tok",
        payload={
            "cancellationReason": "Any Reason",
            "cancellationExplanation": "",
        },
    )
    assert "status" in resp
    assert captured["kwargs"]["params"] == {"token": "tok"}
    assert captured["kwargs"]["json"] == {
        "cancellationReason": "Any Reason",
        "cancellationExplanation": "",
    }


@pytest.mark.asyncio
async def test_cancel_order_maps_400_status(monkeypatch):
    class FakeResponse:
        status_code = 400

        def json(self):
            return {"status": "Cannot cancel after medic is assigned"}

    class FakeClient:
        async def patch(self, *args, **kwargs):
            return FakeResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.httpx.AsyncClient",
        lambda **kwargs: FakeClient(),
    )
    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.settings.ORANGE_HEALTH_API_KEY",
        "key",
    )
    monkeypatch.setattr(
        "modules.diagnostics.orange_health.client.settings.ORANGE_HEALTH_BASE_URL",
        "https://example.test",
    )

    with pytest.raises(OrangeHealthApiError) as exc:
        await cancel_order(
            request_id="BLR1",
            token="tok",
            payload={"cancellationReason": "Any Reason", "cancellationExplanation": ""},
        )
    assert exc.value.status_code == 400
    assert "medic" in str(exc.value).lower()
