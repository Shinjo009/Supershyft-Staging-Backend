"""WhatAPI Meta messaging client (template fetch + send)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


def _auth_headers() -> dict[str, str]:
    token = (settings.WHATAPI_ACCESS_TOKEN or "").strip()
    return {"Authorization": f"Bearer {token}"}


def _messages_url() -> str:
    domain = settings.WHATAPI_DOMAIN.rstrip("/")
    version = settings.WHATAPI_VERSION.strip("/")
    phone_id = settings.WHATAPI_PHONE_NUMBER_ID.strip()
    return f"{domain}/api/meta/{version}/{phone_id}/messages"


def _templates_url(*, name: str) -> str:
    domain = settings.WHATAPI_DOMAIN.rstrip("/")
    version = settings.WHATAPI_VERSION.strip("/")
    waba_id = settings.WHATAPI_WABA_ID.strip()
    return f"{domain}/api/meta/{version}/{waba_id}/message_templates?name={name}"


def normalize_whatsapp_number(phone: str, *, country_code: str | None = None) -> str:
    digits_only = "".join(ch for ch in phone if ch.isdigit())
    if not digits_only:
        return ""
    cc = (country_code or settings.OTP_COUNTRY_CODE or "91").strip()
    if len(digits_only) == 10:
        return f"{cc}{digits_only}"
    if digits_only.startswith(cc):
        return digits_only
    if len(digits_only) > 10:
        return digits_only
    return f"{cc}{digits_only}"


async def fetch_message_template(name: str) -> dict[str, Any] | None:
    """Return first matching template dict from WhatAPI, or None."""
    if not settings.WHATAPI_DOMAIN or not settings.WHATAPI_ACCESS_TOKEN:
        return None
    url = _templates_url(name=name)
    async with httpx.AsyncClient(timeout=settings.WHATAPI_TIMEOUT_SECONDS) as client:
        resp = await client.get(url, headers=_auth_headers())
        resp.raise_for_status()
        data = resp.json()
    if isinstance(data, dict):
        items = data.get("data")
        if isinstance(items, list) and items:
            first = items[0]
            return first if isinstance(first, dict) else None
    return None


def template_language_code(template: dict[str, Any] | None, *, fallback: str = "en") -> str:
    if not template:
        return fallback
    language = template.get("language")
    if isinstance(language, str) and language.strip():
        return language.strip()
    if isinstance(language, dict):
        code = language.get("code")
        if isinstance(code, str) and code.strip():
            return code.strip()
    return fallback


async def send_template_message(*, to: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST template message; returns parsed JSON response."""
    url = _messages_url()
    async with httpx.AsyncClient(timeout=settings.WHATAPI_TIMEOUT_SECONDS) as client:
        resp = await client.post(url, headers={**_auth_headers(), "Content-Type": "application/json"}, json=body)
        resp.raise_for_status()
        data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("WhatAPI send returned non-object JSON")
    return data


def extract_queue_id(response: dict[str, Any]) -> str | None:
    message = response.get("message")
    if isinstance(message, dict):
        queue_id = message.get("queue_id")
        if queue_id:
            return str(queue_id)
    queue_id = response.get("queue_id")
    return str(queue_id) if queue_id else None
