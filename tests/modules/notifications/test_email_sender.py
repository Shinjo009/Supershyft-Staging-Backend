"""Tests for SMTP notification email sender."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core.exceptions import AppError
from modules.notifications.email_sender import send_notification_email
from modules.notifications.models import NotificationService


@pytest.mark.asyncio
async def test_send_notification_email_interpolates_and_sends(monkeypatch):
    monkeypatch.setattr("modules.notifications.email_sender.settings.SMTP_HOST", "smtp.test")
    monkeypatch.setattr("modules.notifications.email_sender.settings.SMTP_USERNAME", "user@test")
    monkeypatch.setattr("modules.notifications.email_sender.settings.SMTP_PASSWORD", "secret")
    monkeypatch.setattr("modules.notifications.email_sender.settings.SMTP_FROM_EMAIL", "from@test")
    monkeypatch.setattr("modules.notifications.email_sender.settings.SMTP_FROM_NAME", "Test")
    monkeypatch.setattr("modules.notifications.email_sender.settings.SMTP_PORT", 587)
    monkeypatch.setattr("modules.notifications.email_sender.settings.SMTP_USE_TLS", True)
    monkeypatch.setattr("modules.notifications.email_sender.settings.SMTP_TIMEOUT_SECONDS", 30)

    service = NotificationService(
        service_key="email-test",
        display_name="Email",
        channel="email",
        webhook_path="/email-test",
        is_active=True,
        email_subject="Hi {{first_name}}",
        email_body="Body {{otp}}",
        email_html="<p>Body {{otp}}</p>",
    )

    with patch(
        "modules.notifications.email_sender.aiosmtplib.send",
        new_callable=AsyncMock,
    ) as mock_send:
        await send_notification_email(
            service,
            {"email": "recipient@test.com", "first_name": "Ada", "otp": "9999"},
        )

    mock_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_notification_email_missing_recipient(monkeypatch):
    monkeypatch.setattr("modules.notifications.email_sender.settings.SMTP_HOST", "smtp.test")
    monkeypatch.setattr("modules.notifications.email_sender.settings.SMTP_USERNAME", "user@test")

    service = NotificationService(
        service_key="email-test",
        display_name="Email",
        channel="email",
        webhook_path="/email-test",
        is_active=True,
        email_subject="Hi",
        email_body="Body",
    )

    with pytest.raises(AppError) as exc:
        await send_notification_email(service, {"first_name": "Ada"})
    assert exc.value.status_code == 400
