"""Tests for direct send dispatch path."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from core.config import settings
from modules.notifications.whatapi_client import WhatApiSendResult
from modules.users.models import User

TEST_NOTIFICATION_API_KEY = "test-notif-direct-send-key"


def _api_key_header() -> dict[str, str]:
    return {"x-api-key": TEST_NOTIFICATION_API_KEY}


@pytest.mark.asyncio
async def test_dispatch_direct_whatsapp_queued(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "NOTIFICATION_API_KEY", TEST_NOTIFICATION_API_KEY)
    monkeypatch.setattr(settings, "NOTIFICATION_USE_DIRECT_SEND", True)

    await test_db_session.execute(
        text(
            "INSERT INTO notification_services "
            "(service_key, display_name, channel, webhook_path, is_active, template_name, template_variables, "
            "require_blood_report_url, require_bio_ai_report_url, require_participant_detail, require_otp) "
            "VALUES ('direct-wa-test', 'Direct WA', 'whatsapp', '/direct-wa-test', true, 'otp', "
            "'[\"{{otp}}\"]'::jsonb, false, false, false, true) "
            "ON CONFLICT (service_key) DO UPDATE SET template_name = EXCLUDED.template_name, "
            "template_variables = EXCLUDED.template_variables"
        )
    )
    test_db_session.add(
        User(user_id=88001, age=30, phone="8800100000", status="active", first_name="Test")
    )
    await test_db_session.commit()

    mock_components = AsyncMock(
        return_value=("otp_new", "en", [{"type": "body", "parameters": []}])
    )
    mock_send = AsyncMock(
        return_value=WhatApiSendResult(queue_id="q-abc", message_status="queued", raw={})
    )

    with (
        patch(
            "modules.notifications.direct_dispatch.build_whatsapp_components",
            mock_components,
        ),
        patch(
            "modules.notifications.direct_dispatch.WhatApiClient.send_template_message",
            mock_send,
        ),
    ):
        response = await async_client.post(
            "/notifications/dispatch",
            headers=_api_key_header(),
            json={
                "service_key": "direct-wa-test",
                "user_ids": [88001],
                "otp": "123456",
            },
        )

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["status"] == "queued"
    assert data["queue_id"] == "q-abc"


@pytest.mark.asyncio
async def test_dispatch_uses_n8n_when_direct_send_disabled(
    async_client, test_db_session, monkeypatch
):
    monkeypatch.setattr(settings, "NOTIFICATION_API_KEY", TEST_NOTIFICATION_API_KEY)
    monkeypatch.setattr(settings, "NOTIFICATION_USE_DIRECT_SEND", False)

    service_key = "direct-n8n-fallback-test"
    test_db_session.add(
        User(user_id=88002, age=30, phone="8800200000", status="active", first_name="Test")
    )
    await test_db_session.execute(
        text(
            "INSERT INTO notification_services "
            "(service_key, display_name, channel, webhook_path, is_active, "
            "require_blood_report_url, require_bio_ai_report_url, require_participant_detail, require_otp) "
            "VALUES (:sk, 'N8N', 'email', '/n8n-fallback', true, false, false, false, false) "
            "ON CONFLICT (service_key) DO UPDATE SET webhook_path = EXCLUDED.webhook_path"
        ),
        {"sk": service_key},
    )
    await test_db_session.commit()

    mock_post = MagicMock()

    class _FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {"message": "ok"}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json=None):
            mock_post(url=url, json=json)
            return _FakeResponse()

    monkeypatch.setattr("modules.notifications.service.httpx.AsyncClient", _FakeClient)

    response = await async_client.post(
        "/notifications/dispatch",
        headers=_api_key_header(),
        json={"service_key": service_key, "user_ids": [88002]},
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["status"] == "pending"
    mock_post.assert_called_once()
