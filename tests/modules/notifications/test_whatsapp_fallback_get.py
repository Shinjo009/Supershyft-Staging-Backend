"""Tests for legacy WhatAPI GET fallback."""

from __future__ import annotations

import pytest

from modules.notifications import whatsapp_fallback_get


@pytest.mark.asyncio
async def test_send_whatsapp_fallback_get_builds_otp_message(monkeypatch):
    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"accepted": True}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params=None):
            captured["url"] = url
            captured["params"] = params
            return _Resp()

    monkeypatch.setattr(whatsapp_fallback_get.settings, "WHATAPI_FALLBACK_WEBHOOK_URL", "https://fallback.test/hook")
    monkeypatch.setattr(whatsapp_fallback_get.httpx, "AsyncClient", lambda *a, **k: _Client())

    resp = await whatsapp_fallback_get.send_whatsapp_fallback_get_otp(phone="8762830757", otp="654321")
    assert whatsapp_fallback_get.fallback_accepted(resp) is True
    assert captured["params"]["message"] == "otp,654321"
    assert captured["params"]["number"] == "918762830757"


def test_fallback_accepted_false():
    assert whatsapp_fallback_get.fallback_accepted({"accepted": False}) is False
