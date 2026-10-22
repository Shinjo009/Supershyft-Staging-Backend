"""Tests for WhatsApp fallback GET sender."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.notifications.whatsapp_fallback_get import send_whatsapp_fallback_get


@pytest.mark.asyncio
async def test_fallback_get_accepted(monkeypatch):
    monkeypatch.setattr(
        "modules.notifications.whatsapp_fallback_get.settings.WHATAPI_FALLBACK_WEBHOOK_URL",
        "https://fallback.example/webhook",
    )

    mock_response = MagicMock()
    mock_response.json.return_value = {"accepted": True}
    mock_response.text = "ok"
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch(
            "modules.notifications.whatsapp_fallback_get.persist_integration_sync_log_isolated",
            AsyncMock(return_value=1),
        ),
        patch(
            "modules.notifications.whatsapp_fallback_get.finalize_integration_sync_log_isolated",
            AsyncMock(),
        ),
        patch(
            "modules.notifications.whatsapp_fallback_get.httpx.AsyncClient",
            return_value=mock_client,
        ),
    ):
        ok = await send_whatsapp_fallback_get(
            phone="9876543210",
            message="Hello, world",
        )

    assert ok is True
    mock_client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_fallback_get_not_accepted(monkeypatch):
    monkeypatch.setattr(
        "modules.notifications.whatsapp_fallback_get.settings.WHATAPI_FALLBACK_WEBHOOK_URL",
        "https://fallback.example/webhook",
    )

    mock_response = MagicMock()
    mock_response.json.return_value = {"accepted": False}
    mock_response.text = "rejected"
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch(
            "modules.notifications.whatsapp_fallback_get.persist_integration_sync_log_isolated",
            AsyncMock(return_value=1),
        ),
        patch(
            "modules.notifications.whatsapp_fallback_get.finalize_integration_sync_log_isolated",
            AsyncMock(),
        ),
        patch(
            "modules.notifications.whatsapp_fallback_get.httpx.AsyncClient",
            return_value=mock_client,
        ),
    ):
        ok = await send_whatsapp_fallback_get(
            phone="9876543210",
            message="Hello",
        )

    assert ok is False
