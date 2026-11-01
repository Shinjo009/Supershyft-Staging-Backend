"""Tests for WhatsApp template admin proxy."""

from __future__ import annotations

import pytest

from modules.notifications import whatsapp_template_proxy


@pytest.mark.asyncio
async def test_fetch_whatsapp_template_for_admin_normalizes(monkeypatch):
    async def fake_fetch(name: str):
        assert name == "camp17"
        return {
            "name": "camp17",
            "status": "APPROVED",
            "category": "UTILITY",
            "language": "en",
            "components": [
                {
                    "type": "BODY",
                    "example": {"body_text": [["a", "b", "c"]]},
                }
            ],
        }

    monkeypatch.setattr(
        whatsapp_template_proxy, "fetch_message_template", fake_fetch
    )
    data = await whatsapp_template_proxy.fetch_whatsapp_template_for_admin("camp17")
    assert data is not None
    assert data["status"] == "APPROVED"
    assert data["components"][0]["parameter_count"] == 3
