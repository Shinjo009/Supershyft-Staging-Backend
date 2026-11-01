"""Direct notification delivery (WhatAPI POST/SMTP) when service content is configured."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from modules.audit.cron_sync_logging import (
    finalize_integration_sync_log_isolated,
    persist_integration_sync_log_isolated,
)
from modules.notifications.email_sender import send_email
from modules.notifications.models import NotificationService
from modules.notifications.whatapi_client import (
    extract_queue_id,
    fetch_message_template,
    normalize_whatsapp_number,
    send_template_message,
    template_language_code,
)
from modules.notifications.whatsapp_fallback_get import fallback_accepted, send_whatsapp_fallback_get
from modules.notifications.whatsapp_template_builder import (
    build_dispatch_context,
    build_template_components,
    build_template_message_body,
)
from core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DirectDispatchOutcome:
    status: str
    message: str
    queue_id: str | None = None
    completed_at: datetime | None = None


def service_has_direct_whatsapp(svc: NotificationService) -> bool:
    name = (svc.template_name or "").strip()
    return bool(name) and svc.template_variables is not None


def service_has_direct_email(svc: NotificationService) -> bool:
    return bool(
        (svc.email_subject or "").strip()
        or (svc.email_body or "").strip()
        or (svc.email_html or "").strip()
    )


def service_uses_direct_delivery(svc: NotificationService) -> bool:
    if svc.channel == "whatsapp":
        return service_has_direct_whatsapp(svc)
    if svc.channel == "email":
        return service_has_direct_email(svc)
    return False


def _first_recipient(members: list[dict]) -> dict:
    return members[0] if members else {}


async def try_direct_delivery(
    svc: NotificationService,
    *,
    notification_id: int,
    members: list[dict],
    participant_details: dict | None,
    engagement_id: int | None,
    sync_log_user_id: int | None,
) -> DirectDispatchOutcome | None:
    if not service_uses_direct_delivery(svc):
        return None

    if svc.channel == "email":
        return await _deliver_email_direct(
            svc,
            notification_id=notification_id,
            members=members,
            participant_details=participant_details,
            engagement_id=engagement_id,
            sync_log_user_id=sync_log_user_id,
        )
    return await _deliver_whatsapp_direct(
        svc,
        notification_id=notification_id,
        members=members,
        participant_details=participant_details,
        engagement_id=engagement_id,
        sync_log_user_id=sync_log_user_id,
    )


async def _deliver_email_direct(
    svc: NotificationService,
    *,
    notification_id: int,
    members: list[dict],
    participant_details: dict | None,
    engagement_id: int | None,
    sync_log_user_id: int | None,
) -> DirectDispatchOutcome:
    recipient = _first_recipient(members)
    to_email = str(recipient.get("email") or "").strip()
    if not to_email:
        return DirectDispatchOutcome(status="failed", message="No recipient email for direct SMTP send")

    context = build_dispatch_context(members, participant_details=participant_details)
    subject = (svc.email_subject or "Notification").strip()
    body = (svc.email_body or svc.email_html or "").strip()
    html = (svc.email_html or "").strip() or None

    sync_log_id = await persist_integration_sync_log_isolated(
        provider="internal",
        api_url=f"smtp://{settings.SMTP_HOST or 'localhost'}",
        engagement_id=engagement_id,
        user_id=sync_log_user_id,
        request_payload={
            "notification_id": notification_id,
            "to": to_email,
            "service_key": svc.service_key,
        },
    )
    try:
        msg = await send_email(
            to_email=to_email,
            subject_template=subject,
            body_template=body,
            html_template=html,
            context=context,
        )
        now = datetime.now(timezone.utc)
        await finalize_integration_sync_log_isolated(
            sync_log_id=sync_log_id,
            status="success",
            response_payload={"message": msg},
        )
        return DirectDispatchOutcome(status="sent", message=msg, completed_at=now)
    except Exception as exc:
        logger.exception("Direct SMTP send failed")
        await finalize_integration_sync_log_isolated(
            sync_log_id=sync_log_id,
            status="failed",
            error_message=str(exc),
        )
        return DirectDispatchOutcome(status="failed", message=f"SMTP send failed: {exc}")


async def _deliver_whatsapp_direct(
    svc: NotificationService,
    *,
    notification_id: int,
    members: list[dict],
    participant_details: dict | None,
    engagement_id: int | None,
    sync_log_user_id: int | None,
) -> DirectDispatchOutcome:
    recipient = _first_recipient(members)
    phone = str(recipient.get("phone") or "").strip()
    otp = str(recipient.get("otp") or "").strip()
    if not phone:
        return DirectDispatchOutcome(status="failed", message="No recipient phone for direct WhatsApp send")

    template_name = (svc.template_name or "").strip()
    context = build_dispatch_context(members, participant_details=participant_details)
    components = build_template_components(svc.template_variables, context)

    try:
        template_meta = await fetch_message_template(template_name)
    except Exception as exc:
        logger.warning("Template fetch failed for %s: %s", template_name, exc)
        template_meta = None

    language_code = template_language_code(template_meta, fallback="en")
    to_number = normalize_whatsapp_number(phone)
    body = build_template_message_body(
        to_phone=to_number,
        template_name=template_name,
        language_code=language_code,
        components=components,
    )

    post_url = (
        f"{settings.WHATAPI_DOMAIN.rstrip('/')}/api/meta/"
        f"{settings.WHATAPI_VERSION.strip('/')}/{settings.WHATAPI_PHONE_NUMBER_ID.strip()}/messages"
    )
    sync_log_id = await persist_integration_sync_log_isolated(
        provider="whatapi",
        api_url=post_url,
        engagement_id=engagement_id,
        user_id=sync_log_user_id,
        request_payload={"notification_id": notification_id, "body": body},
    )

    try:
        response = await send_template_message(to=to_number, body=body)
        queue_id = extract_queue_id(response)
        await finalize_integration_sync_log_isolated(
            sync_log_id=sync_log_id,
            status="success",
            response_payload=response,
        )
        if queue_id:
            return DirectDispatchOutcome(
                status="queued",
                message="WhatsApp template accepted (queued)",
                queue_id=queue_id,
            )
        return DirectDispatchOutcome(
            status="queued",
            message="WhatsApp template accepted",
            queue_id=None,
        )
    except Exception as post_exc:
        logger.warning("WhatAPI POST failed, attempting GET fallback: %s", post_exc)
        await finalize_integration_sync_log_isolated(
            sync_log_id=sync_log_id,
            status="failed",
            error_message=str(post_exc),
        )

    fallback_log_id = await persist_integration_sync_log_isolated(
        provider="whatapi",
        api_url=settings.WHATAPI_FALLBACK_WEBHOOK_URL or "whatapi-fallback",
        engagement_id=engagement_id,
        user_id=sync_log_user_id,
        request_payload={"notification_id": notification_id, "phone": phone, "otp": otp},
    )
    try:
        fallback_resp = await send_whatsapp_fallback_get(phone=phone, otp=otp)
        if fallback_accepted(fallback_resp):
            now = datetime.now(timezone.utc)
            await finalize_integration_sync_log_isolated(
                sync_log_id=fallback_log_id,
                status="success",
                response_payload=fallback_resp,
            )
            return DirectDispatchOutcome(
                status="sent",
                message="WhatsApp GET fallback accepted",
                completed_at=now,
            )
        await finalize_integration_sync_log_isolated(
            sync_log_id=fallback_log_id,
            status="failed",
            response_payload=fallback_resp,
            error_message="GET fallback not accepted",
        )
        return DirectDispatchOutcome(status="failed", message="WhatsApp GET fallback rejected")
    except Exception as fb_exc:
        await finalize_integration_sync_log_isolated(
            sync_log_id=fallback_log_id,
            status="failed",
            error_message=str(fb_exc),
        )
        return DirectDispatchOutcome(status="failed", message=f"WhatsApp delivery failed: {fb_exc}")
