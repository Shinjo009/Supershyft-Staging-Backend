"""Tests for SMTP email sender."""

from __future__ import annotations

import pytest

from modules.notifications import email_sender


@pytest.mark.asyncio
async def test_send_email_interpolates_otp(monkeypatch):
    sent: dict = {}

    def _fake_smtp(**kwargs):
        sent.update(kwargs)

    monkeypatch.setattr(email_sender, "_send_smtp_sync", _fake_smtp)
    monkeypatch.setattr(email_sender.settings, "SMTP_HOST", "smtp.test")

    msg = await email_sender.send_email(
        to_email="user@test.example",
        subject_template="Code {{otp}}",
        body_template="Your code is {{otp}}",
        html_template=None,
        context={"otp": {"otp": "112233"}},
    )
    assert "user@test.example" in msg
    assert sent["subject"] == "Code 112233"
    assert sent["body_text"] == "Your code is 112233"
