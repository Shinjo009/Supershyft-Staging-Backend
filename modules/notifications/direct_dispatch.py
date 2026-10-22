"""Direct send path (WhatAPI + SMTP) for NotificationsService."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppError
from modules.notifications.email_sender import send_notification_email
from modules.notifications.models import Notification, NotificationService
from modules.notifications.repository import NotificationsRepository
from modules.notifications.template_variables import build_dispatch_context
from modules.notifications.whatapi_client import WhatApiClient
from modules.notifications.whatsapp_fallback_get import send_whatsapp_fallback_get
from modules.notifications.whatsapp_template_builder import (
    build_fallback_message_and_medialink,
    build_whatsapp_components,
)

logger = logging.getLogger(__name__)


async def execute_direct_dispatch(
    db: AsyncSession,
    *,
    repo: NotificationsRepository,
    notification: Notification,
    svc: NotificationService,
    members: list[dict[str, Any]],
    participant_details: dict | None,
    engagement_id: int | None,
    sync_log_user_id: int | None,
) -> tuple[str, str, str | None]:
    """Send to all members; return (final_status, message, first_queue_id)."""
    client = WhatApiClient()
    errors: list[str] = []
    first_queue_id: str | None = None
    any_queued = False
    all_terminal_success = True

    for member in members:
        context = build_dispatch_context(
            member,
            participant_details=participant_details,
            engagement_id=engagement_id,
        )
        try:
            if svc.channel == "whatsapp":
                phone = str(member.get("phone") or "").strip()
                if not phone:
                    raise AppError(
                        status_code=400,
                        error_code="INVALID_INPUT",
                        message="Member phone is required for WhatsApp",
                    )
                try:
                    api_name, language_code, components = await build_whatsapp_components(
                        svc,
                        context,
                        client=client,
                        engagement_id=engagement_id,
                        user_id=sync_log_user_id,
                    )
                    result = await client.send_template_message(
                        to=phone,
                        template_name=api_name,
                        language_code=language_code,
                        components=components,
                        engagement_id=engagement_id,
                        user_id=sync_log_user_id,
                    )
                    if result.queue_id:
                        any_queued = True
                        if first_queue_id is None:
                            first_queue_id = result.queue_id
                        continue
                except Exception as post_exc:
                    logger.warning("WhatAPI POST failed, trying fallback: %s", post_exc)

                message, medialink = build_fallback_message_and_medialink(svc, context)
                accepted = await send_whatsapp_fallback_get(
                    phone=phone,
                    message=message,
                    medialink=medialink,
                    engagement_id=engagement_id,
                    user_id=sync_log_user_id,
                )
                if not accepted:
                    all_terminal_success = False
                    errors.append(f"WhatsApp fallback rejected for {phone}")
            elif svc.channel == "email":
                await send_notification_email(svc, context)
            else:
                raise AppError(
                    status_code=400,
                    error_code="INVALID_INPUT",
                    message=f"Unsupported channel '{svc.channel}'",
                )
        except AppError as exc:
            all_terminal_success = False
            errors.append(exc.message)
        except Exception as exc:
            all_terminal_success = False
            errors.append(str(exc))

    if errors:
        final_status = "failed"
        message = "; ".join(errors)
    elif any_queued:
        final_status = "queued"
        message = "WhatsApp message queued"
    else:
        final_status = "sent"
        message = "Direct send completed"

    now = datetime.now(timezone.utc)
    values: dict[str, Any] = {
        "status": final_status,
        "message": message,
        "dispatched_at": now,
        "queue_id": first_queue_id,
    }
    if final_status == "sent":
        values["completed_at"] = now
    if final_status == "failed":
        values["queue_id"] = None

    await repo.update_notification(
        db,
        notification_id=notification.notification_id,
        values=values,
    )
    return final_status, message, first_queue_id
