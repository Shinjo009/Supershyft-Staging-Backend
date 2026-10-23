"""Tests for WhatsApp template builder helpers."""

from __future__ import annotations

from types import SimpleNamespace

from modules.notifications.whatsapp_template_builder import build_fallback_message_and_medialink


def test_fallback_otpmsg_matches_legacy_get_format():
    """Hello {otp} is your verification code — two body slots on otpmsg template."""
    svc = SimpleNamespace(
        template_name="otpmsg",
        template_variables=["{{otp}}", "verification code"],
    )
    message, medialink = build_fallback_message_and_medialink(svc, {"otp": "123456"})
    assert message == "otpmsg,123456,verification code"
    assert medialink is None
