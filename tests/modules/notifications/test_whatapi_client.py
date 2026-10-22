"""Unit tests for WhatApiClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import settings
from modules.notifications.whatapi_client import WhatApiClient, normalize_whatsapp_phone


def test_normalize_whatsapp_phone_india_10_digit():
    assert normalize_whatsapp_phone("9876543210", country_code="91") == "919876543210"


def test_normalize_whatsapp_phone_already_prefixed():
    assert normalize_whatsapp_phone("919876543210", country_code="91") == "919876543210"


@pytest.mark.asyncio
async def test_send_template_message_parses_queue_id(monkeypatch):
    monkeypatch.setattr(settings, "WHATAPI_DOMAIN", "https://crm.example")
    monkeypatch.setattr(settings, "WHATAPI_VERSION", "v19.0")
    monkeypatch.setattr(settings, "WHATAPI_PHONE_NUMBER_ID", "phone123")
    monkeypatch.setattr(settings, "WHATAPI_ACCESS_TOKEN", "token")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "message": {"queue_id": "q-99", "message_status": "queued"},
    }
    mock_response.text = "ok"

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch(
            "modules.notifications.whatapi_client.persist_integration_sync_log_isolated",
            AsyncMock(return_value=1),
        ),
        patch(
            "modules.notifications.whatapi_client.finalize_integration_sync_log_isolated",
            AsyncMock(),
        ),
        patch(
            "modules.notifications.whatapi_client.httpx.AsyncClient",
            return_value=mock_client,
        ),
    ):
        client = WhatApiClient()
        result = await client.send_template_message(
            to="9876543210",
            template_name="otp",
            language_code="en",
            components=[],
        )

    assert result.queue_id == "q-99"
    assert result.message_status == "queued"


@pytest.mark.asyncio
async def test_get_message_template_logs_integration_sync(monkeypatch):
    monkeypatch.setattr(settings, "WHATAPI_DOMAIN", "https://crm.example")
    monkeypatch.setattr(settings, "WHATAPI_VERSION", "v19.0")
    monkeypatch.setattr(settings, "WHATAPI_WABA_ID", "waba123")
    monkeypatch.setattr(settings, "WHATAPI_ACCESS_TOKEN", "token")
    monkeypatch.setattr(settings, "WHATAPI_API_KEY", "key")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": [{"name": "otp_new", "status": "APPROVED", "language": "en"}]}
    mock_response.text = "ok"

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    persist = AsyncMock(return_value=42)
    finalize = AsyncMock()

    with (
        patch("modules.notifications.whatapi_client.persist_integration_sync_log_isolated", persist),
        patch("modules.notifications.whatapi_client.finalize_integration_sync_log_isolated", finalize),
        patch("modules.notifications.whatapi_client.httpx.AsyncClient", return_value=mock_client),
    ):
        client = WhatApiClient()
        meta = await client.get_message_template("otp_new", engagement_id=1, user_id=2)

    assert meta["name"] == "otp_new"
    persist.assert_called_once()
    finalize.assert_called_once()