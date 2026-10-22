"""SMTP email sender for notification_services content."""

from __future__ import annotations

import logging
from typing import Any
from email.message import EmailMessage

import aiosmtplib

from core.config import settings
from core.exceptions import AppError
from modules.notifications.models import NotificationService
from modules.notifications.template_variables import resolve_text

logger = logging.getLogger(__name__)


async def send_notification_email(
    service: NotificationService,
    context: dict[str, Any],
) -> None:
    if not settings.SMTP_HOST or not settings.SMTP_USERNAME:
        raise AppError(
            status_code=503,
            error_code="EXTERNAL_SERVICE_UNAVAILABLE",
            message="SMTP is not configured",
        )

    subject = resolve_text(service.email_subject or "Notification", context)
    html = (service.email_html or "").strip()
    plain = (service.email_body or "").strip()

    if not html and not plain:
        raise AppError(
            status_code=400,
            error_code="INVALID_INPUT",
            message=f"Service '{service.service_key}' has no email body for direct send",
        )

    to_email = str(context.get("email") or "").strip()
    if not to_email:
        raise AppError(
            status_code=400,
            error_code="INVALID_INPUT",
            message="Recipient email is required",
        )

    msg = EmailMessage()
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    if html:
        msg.set_content(plain or " ")
        msg.add_alternative(html, subtype="html")
    else:
        msg.set_content(plain)

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USERNAME,
            password=settings.SMTP_PASSWORD,
            start_tls=settings.SMTP_USE_TLS,
            timeout=settings.SMTP_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.exception("SMTP send failed")
        raise AppError(
            status_code=503,
            error_code="EXTERNAL_SERVICE_UNAVAILABLE",
            message="Failed to send email",
        ) from exc
