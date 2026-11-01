"""Shared async seeds for notification tests (post Prompt 6 cutover)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.notifications.events_catalog import LEGACY_EVENT_CODE_MAP
from modules.notifications.migration_0187_bindings import default_recipient_for_event

# Minimal template blobs for dispatch-hint detection (see service_dispatch_hints).
_SIMPLE_BODY_VAR = [{"component": "body", "parameters": [{"type": "text", "source": "{{user.first_name}}"}]}]
_SESSION_DETAILS_VARS = [
    {
        "component": "body",
        "parameters": [{"type": "text", "source": "{{session_details.slot}}"}],
    }
]
_PARTICIPANT_DETAIL_VARS = [
    {
        "component": "body",
        "parameters": [{"type": "text", "source": "{{participant_details.name}}"}],
    }
]
_OTP_VARS = [{"component": "body", "parameters": [{"type": "text", "source": "{{otp.otp}}"}]}]
_BLOOD_REPORT_VARS = [
    {"component": "body", "parameters": [{"type": "text", "source": "{{blood_report_url}}"}]}
]
_BIO_AI_REPORT_VARS = [
    {"component": "body", "parameters": [{"type": "text", "source": "{{bio_ai_report_url}}"}]}
]
_EXTERNAL_LINK_VARS = [
    {"component": "body", "parameters": [{"type": "text", "source": "{{external_link}}"}]}
]


def catalog_event_code(code: str) -> str:
    """Map legacy engagement/auto event codes to catalog codes."""
    raw = (code or "").strip()
    return LEGACY_EVENT_CODE_MAP.get(raw, raw)


def engagement_stored_event_code(code: str) -> str:
    """Event code stored on engagement_notifications (legacy backfill shape)."""
    return (code or "").strip()


def recipient_type_for_event(code: str, *, override: str | None = None) -> str:
    if override:
        return override
    return default_recipient_for_event(catalog_event_code(code))


def _service_config_items(
    service_keys: list[str] | str,
    *,
    external_link: str | None = None,
) -> list[dict[str, Any]]:
    if isinstance(service_keys, str):
        keys = [k.strip() for k in service_keys.split(",") if k.strip()]
    else:
        keys = [str(k).strip() for k in service_keys if str(k).strip()]
    return [{"service_key": key, "external_link": external_link} for key in keys]


async def upsert_notification_service(
    session: AsyncSession,
    *,
    service_key: str,
    channel: str = "whatsapp",
    display_name: str | None = None,
    is_active: bool = True,
    template_name: str | None = None,
    template_variables: list | dict | None = None,
    email_subject: str | None = None,
    email_body: str | None = None,
    email_html: str | None = None,
    hint: str | None = None,
) -> None:
    """Insert notification_services row with direct-delivery content."""
    dn = display_name or service_key
    tv = template_variables
    if tv is None and channel == "whatsapp":
        if hint == "session_details":
            tv = _SESSION_DETAILS_VARS
        elif hint == "participant_detail":
            tv = _PARTICIPANT_DETAIL_VARS
        elif hint == "otp":
            tv = _OTP_VARS
        elif hint == "blood_report":
            tv = _BLOOD_REPORT_VARS
        elif hint == "bio_ai_report":
            tv = _BIO_AI_REPORT_VARS
        elif hint == "external_link":
            tv = _EXTERNAL_LINK_VARS
        else:
            tv = _SIMPLE_BODY_VAR
    if channel == "whatsapp" and not template_name:
        template_name = "test_template"

    await session.execute(
        text(
            "INSERT INTO notification_services "
            "(service_key, display_name, channel, is_active, template_name, template_variables, "
            "email_subject, email_body, email_html) "
            "VALUES (:sk, :dn, :ch, :active, :tn, CAST(:tv AS jsonb), :es, :eb, :eh) "
            "ON CONFLICT (service_key) DO UPDATE SET "
            "display_name = EXCLUDED.display_name, "
            "channel = EXCLUDED.channel, "
            "is_active = EXCLUDED.is_active, "
            "template_name = EXCLUDED.template_name, "
            "template_variables = EXCLUDED.template_variables, "
            "email_subject = EXCLUDED.email_subject, "
            "email_body = EXCLUDED.email_body, "
            "email_html = EXCLUDED.email_html"
        ),
        {
            "sk": service_key,
            "dn": dn,
            "ch": channel,
            "active": is_active,
            "tn": template_name if channel == "whatsapp" else None,
            "tv": json.dumps(tv) if tv is not None else None,
            "es": email_subject,
            "eb": email_body,
            "eh": email_html,
        },
    )


async def upsert_notification_event_binding(
    session: AsyncSession,
    *,
    event_code: str,
    recipient_type: str,
    notification_services: list[str] | str,
    event_name: str | None = None,
    is_active: bool = True,
) -> None:
    """Global binding in notification_events."""
    catalog = catalog_event_code(event_code)
    keys = _service_config_items(notification_services)
    svc_json = json.dumps([item["service_key"] for item in keys])
    await session.execute(
        text(
            "INSERT INTO notification_events "
            "(event_code, event_name, recipient_type, notification_services, is_active) "
            "VALUES (:code, :name, :rt, CAST(:svc AS jsonb), :active) "
            "ON CONFLICT (event_code, recipient_type) DO UPDATE SET "
            "notification_services = EXCLUDED.notification_services, "
            "is_active = EXCLUDED.is_active"
        ),
        {
            "code": catalog,
            "name": event_name or catalog,
            "rt": recipient_type,
            "svc": svc_json,
            "active": is_active,
        },
    )


async def upsert_engagement_notification(
    session: AsyncSession,
    *,
    engagement_id: int,
    event_code: str,
    notification_services: list[str] | str | list[dict[str, Any]],
    recipient_type: str | None = None,
    external_link: str | None = None,
) -> None:
    """Per-engagement override in engagement_notifications."""
    stored_code = engagement_stored_event_code(event_code)
    rt = recipient_type_for_event(stored_code, override=recipient_type)
    if isinstance(notification_services, list) and notification_services and isinstance(
        notification_services[0], dict
    ):
        configs = notification_services
    else:
        configs = _service_config_items(notification_services, external_link=external_link)
    services_json = json.dumps(configs)
    await session.execute(
        text(
            "INSERT INTO engagement_notifications "
            "(engagement_id, event_code, recipient_type, notification_services) "
            "VALUES (:eid, :code, :rt, CAST(:services AS jsonb)) "
            "ON CONFLICT (engagement_id, event_code, recipient_type) DO UPDATE SET "
            "notification_services = EXCLUDED.notification_services"
        ),
        {"eid": engagement_id, "code": stored_code, "rt": rt, "services": services_json},
    )


def patch_direct_delivery_success(monkeypatch, *, queue_id: str = "q-test") -> None:
    """Monkeypatch direct delivery to succeed without external APIs."""

    async def _fake_direct(*args, **kwargs):
        from modules.notifications.direct_dispatch import DirectDispatchOutcome

        return DirectDispatchOutcome(status="queued", message="ok", queue_id=queue_id)

    monkeypatch.setattr(
        "modules.notifications.direct_dispatch.try_direct_delivery",
        _fake_direct,
    )
