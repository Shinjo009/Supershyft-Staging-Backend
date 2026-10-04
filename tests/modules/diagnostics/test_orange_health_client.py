"""Tests for Orange Health HTTP client error mapping."""

from __future__ import annotations

import pytest

from modules.diagnostics.orange_health.client import OrangeHealthApiError, check_serviceability


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
