"""Tests for WhatsApp template builder helpers."""

from __future__ import annotations

from types import SimpleNamespace

from modules.notifications.whatsapp_template_builder import build_fallback_message_and_medialink


def test_fallback_otp_service_uses_legacy_otp_prefix():
    svc = SimpleNamespace(
        template_name="otpv4",
        template_variables=["{{otp}}"],
    )
    message, medialink = build_fallback_message_and_medialink(svc, {"otp": "123456"})
    assert message == "otp,123456"
    assert medialink is None
