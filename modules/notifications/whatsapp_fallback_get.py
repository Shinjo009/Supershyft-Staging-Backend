"""Legacy WhatAPI GET webhook sender (comma-separated message)."""

from __future__ import annotations

import logging
from typing import Any
import httpx

from core.config import settings
from modules.audit.cron_sync_logging import (
    finalize_integration_sync_log_isolated,
    persist_integration_sync_log_isolated,
)
from modules.notifications.whatapi_client import normalize_whatsapp_phone
from modules.notifications.whatapi_sync_utils import redact_whatapi_webhook_url

logger = logging.getLogger(__name__)


async def send_whatsapp_fallback_get(
    *,
    phone: str,
    message: str,
    medialink: str | None = None,
    engagement_id: int | None = None,
    user_id: int | None = None,
) -> bool:
    """Return True when WhatAPI responds with accepted=true."""
    base_url = (settings.WHATAPI_FALLBACK_WEBHOOK_URL or settings.OTP_WEBHOOK_URL or "").strip()
    if not base_url:
        logger.error("WhatsApp fallback URL is not configured")
        return False

    number = normalize_whatsapp_phone(phone)
    params: dict[str, Any] = {"number": number, "message": message}
    if medialink:
        params["medialink"] = medialink

    sync_log_id = await persist_integration_sync_log_isolated(
        provider="whatapi",
        api_url=redact_whatapi_webhook_url(base_url),
        engagement_id=engagement_id,
        user_id=user_id,
        request_payload={"params": {**params, "message": message[:200]}},
    )

    try:
        async with httpx.AsyncClient(timeout=settings.WHATAPI_FALLBACK_TIMEOUT_SECONDS) as client:
            resp = await client.get(base_url, params=params)
        data: dict[str, Any]
        try:
            data = resp.json()
        except Exception:
            data = {"status_code": resp.status_code, "body": resp.text}

        accepted = isinstance(data, dict) and data.get("accepted") is True
        await finalize_integration_sync_log_isolated(
            sync_log_id=sync_log_id,
            status="success" if accepted else "failed",
            response_payload=data,
            error_message=None if accepted else resp.text[:500],
        )
        return accepted
    except Exception as exc:
        await finalize_integration_sync_log_isolated(
            sync_log_id=sync_log_id,
            status="failed",
            error_message=str(exc),
        )
        return False
