"""Validate notification service config for direct WhatAPI / SMTP delivery."""

from __future__ import annotations

from core.exceptions import AppError
from modules.notifications.models import NotificationService


def validate_direct_service_config(svc: NotificationService) -> None:
    if svc.channel == "whatsapp":
        if not (svc.template_name or "").strip():
            raise AppError(
                status_code=400,
                error_code="CONFIG_ERROR",
                message=(
                    f"Service '{svc.service_key}' missing template_name for direct WhatsApp send"
                ),
            )
        return

    if svc.channel == "email":
        if not any(
            [
                (svc.email_subject or "").strip(),
                (svc.email_body or "").strip(),
                (svc.email_html or "").strip(),
            ]
        ):
            raise AppError(
                status_code=400,
                error_code="CONFIG_ERROR",
                message=(
                    f"Service '{svc.service_key}' missing email content for direct SMTP send"
                ),
            )