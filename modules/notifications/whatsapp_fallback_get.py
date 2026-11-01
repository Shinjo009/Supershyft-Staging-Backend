"""Legacy WhatAPI GET fallback (comma-separated template message)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from core.config import settings
from modules.notifications.whatapi_client import normalize_whatsapp_number

logger = logging.getLogger(__name__)


async def send_whatsapp_fallback_get(*, phone: str, otp: str, template_prefix: str = "otp") -> dict[str, Any]:
    """GET fallback webhook; returns JSON payload with accepted flag."""
    url = (settings.WHATAPI_FALLBACK_WEBHOOK_URL or "").strip()
    if not url:
        raise ValueError("WHATAPI_FALLBACK_WEBHOOK_URL is not configured")

    number = normalize_whatsapp_number(phone)
    message = f"{template_prefix},{otp}"
    params = {"number": number, "message": message}

    async with httpx.AsyncClient(timeout=settings.WHATAPI_FALLBACK_TIMEOUT_SECONDS) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            data = {"accepted": False, "body": resp.text[:500]}
    if not isinstance(data, dict):
        return {"accepted": False}
    return data


def fallback_accepted(payload: dict[str, Any]) -> bool:
    return payload.get("accepted") is True
