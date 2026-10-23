"""Build Meta WhatsApp template payloads from notification_services content."""

from __future__ import annotations

from typing import Any

from core.exceptions import AppError
from modules.notifications.models import NotificationService
from modules.notifications.template_variables import resolve_binding_value, resolve_text
from modules.notifications.whatapi_client import WhatApiClient

# n8n legacy first-segment aliases → WABA template names (when GET by alias fails)
_TEMPLATE_ALIASES: dict[str, str] = {
    "otp": "otpv4",
}

# WhatAPI GET webhook expects comma message=prefix,var1,... (not always the WABA template name)
_FALLBACK_FIRST_SEGMENT: dict[str, str] = {
    "otp_new": "otp",
    "otpv4": "otp",
    "app_authentication_2": "otp",
    "otpmsg__": "otpmsg",
}

_template_cache: dict[str, dict[str, Any]] = {}


def clear_template_cache() -> None:
    _template_cache.clear()


async def _fetch_template_metadata(
    client: WhatApiClient,
    template_name: str,
    *,
    engagement_id: int | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    if template_name in _template_cache:
        return _template_cache[template_name]

    try:
        meta = await client.get_message_template(
            template_name,
            engagement_id=engagement_id,
            user_id=user_id,
        )
    except AppError:
        alias = _TEMPLATE_ALIASES.get(template_name)
        if alias and alias != template_name:
            meta = await client.get_message_template(
                alias,
                engagement_id=engagement_id,
                user_id=user_id,
            )
        else:
            raise
    _template_cache[template_name] = meta
    return meta


def _template_language(meta: dict[str, Any]) -> str:
    lang = meta.get("language")
    if isinstance(lang, str) and lang:
        return lang
    if isinstance(lang, dict):
        code = lang.get("code")
        if code:
            return str(code)
    return "en"


async def build_whatsapp_components(
    service: NotificationService,
    context: dict[str, Any],
    *,
    client: WhatApiClient | None = None,
    engagement_id: int | None = None,
    user_id: int | None = None,
) -> tuple[str, str, list[dict[str, Any]]]:
    """Return (api_template_name, language_code, components)."""
    template_name = (service.template_name or "").strip()
    if not template_name:
        raise AppError(
            status_code=400,
            error_code="INVALID_INPUT",
            message=f"Service '{service.service_key}' has no template_name for direct send",
        )

    bindings = service.template_variables or []
    api_client = client or WhatApiClient()
    meta = await _fetch_template_metadata(
        api_client,
        template_name,
        engagement_id=engagement_id,
        user_id=user_id,
    )
    status = str(meta.get("status") or "APPROVED").upper()
    if status != "APPROVED":
        raise AppError(
            status_code=400,
            error_code="INVALID_INPUT",
            message=f"Template '{template_name}' is not APPROVED (status={status})",
        )

    api_name = str(meta.get("name") or template_name)
    language_code = _template_language(meta)

    components: list[dict[str, Any]] = []
    body_params: list[dict[str, Any]] = []

    for binding in bindings:
        if isinstance(binding, dict) and binding.get("type") == "header_document":
            link = resolve_binding_value(binding, context).strip()
            if link:
                components.append({
                    "type": "header",
                    "parameters": [
                        {"type": "document", "document": {"link": link}},
                    ],
                })
            continue
        text = resolve_binding_value(binding, context)
        body_params.append({"type": "text", "text": text})

    if body_params:
        components.append({"type": "body", "parameters": body_params})

    return api_name, language_code, components


def build_fallback_message_and_medialink(
    service: NotificationService,
    context: dict[str, Any],
) -> tuple[str, str | None]:
    """Build legacy GET message=template,var1,... and optional medialink."""
    template_name = (service.template_name or "").strip()
    if not template_name:
        raise AppError(
            status_code=400,
            error_code="INVALID_INPUT",
            message="Missing template_name for WhatsApp fallback",
        )

    medialink: str | None = None
    body_parts: list[str] = []

    for binding in service.template_variables or []:
        if isinstance(binding, dict) and binding.get("type") == "header_document":
            medialink = resolve_binding_value(binding, context).strip() or None
            continue
        body_parts.append(resolve_binding_value(binding, context))

    first_segment = _FALLBACK_FIRST_SEGMENT.get(template_name, template_name)
    message = ",".join([first_segment, *body_parts])
    return message, medialink
