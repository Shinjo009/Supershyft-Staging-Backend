"""Tests for WhatAPI client helpers."""

from __future__ import annotations

import pytest

from modules.notifications import whatapi_client


def test_extract_queue_id_from_message_object():
    resp = {
        "messaging_channel": "whatsapp",
        "message": {"queue_id": "887c0d94-e0bd-49fe-98b3-955e81f9ed47", "message_status": "queued"},
    }
    assert whatapi_client.extract_queue_id(resp) == "887c0d94-e0bd-49fe-98b3-955e81f9ed47"


def test_extract_queue_id_top_level():
    assert whatapi_client.extract_queue_id({"queue_id": "abc"}) == "abc"


def test_normalize_whatsapp_number_ten_digits():
    assert whatapi_client.normalize_whatsapp_number("8762830757", country_code="91") == "918762830757"


@pytest.mark.asyncio
async def test_send_template_message_parses_response(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"queue_id": "q-123"}}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, headers=None, json=None):
            assert "messages" in url
            assert json is not None
            return _Resp()

    monkeypatch.setattr(whatapi_client.settings, "WHATAPI_DOMAIN", "https://example.test")
    monkeypatch.setattr(whatapi_client.settings, "WHATAPI_VERSION", "v1")
    monkeypatch.setattr(whatapi_client.settings, "WHATAPI_PHONE_NUMBER_ID", "phone-id")
    monkeypatch.setattr(whatapi_client.settings, "WHATAPI_ACCESS_TOKEN", "token")
    monkeypatch.setattr(whatapi_client.httpx, "AsyncClient", lambda *a, **k: _Client())

    data = await whatapi_client.send_template_message(to="918762830757", body={"type": "template"})
    assert whatapi_client.extract_queue_id(data) == "q-123"
