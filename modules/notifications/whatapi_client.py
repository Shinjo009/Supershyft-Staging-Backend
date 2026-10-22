"""WhatAPI Cloud API client for WhatsApp template messages."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from core.config import settings
from core.exceptions import AppError
from modules.audit.cron_sync_logging import (
    finalize_integration_sync_log_isolated,
    persist_integration_sync_log_isolated,
)

logger = logging.getLogger(__name__)


def normalize_whatsapp_phone(phone: str, *, country_code: str | None = None) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not digits:
        raise AppError(status_code=400, error_code="INVALID_INPUT", message="Invalid phone number")
    cc = country_code or settings.OTP_COUNTRY_CODE or "91"
    if len(digits) == 10:
        return f"{cc}{digits}"
    if digits.startswith(cc):
        return digits
    if len(digits) > 10:
        return digits
    return f"{cc}{digits}"


def normalize_whatapi_domain(domain: str) -> str:
    text = (domain or "").strip().rstrip("/")
    if not text:
        return ""
    if not text.startswith("http"):
        text = f"https://{text}"
    return text


@dataclass
class WhatApiSendResult:
    queue_id: str | None
    message_status: str | None
    raw: dict[str, Any]


class WhatApiClient:
    """HTTP client for WhatAPI Meta-compatible endpoints."""

    def __init__(self) -> None:
        base_domain = normalize_whatapi_domain(settings.WHATAPI_DOMAIN)
        version = settings.WHATAPI_VERSION.strip("/")
        self._api_base = f"{base_domain}/api/meta/{version}/" if base_domain else ""
        self._timeout = settings.WHATAPI_TIMEOUT_SECONDS

    def _auth_headers(self, *, include_api_key: bool = False) -> dict[str, str]:
        headers: dict[str, str] = {}
        token = settings.WHATAPI_ACCESS_TOKEN.strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if include_api_key and settings.WHATAPI_API_KEY.strip():
            headers["API-KEY"] = settings.WHATAPI_API_KEY.strip()
        return headers

    async def get_message_template(
        self,
        name: str,
        *,
        engagement_id: int | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        if not self._api_base or not settings.WHATAPI_WABA_ID:
            raise AppError(
                status_code=503,
                error_code="EXTERNAL_SERVICE_UNAVAILABLE",
                message="WhatAPI is not configured",
            )
        url = (
            f"{self._api_base}{settings.WHATAPI_WABA_ID}/message_templates"
            f"?{urlencode({'name': name})}"
        )
        sync_log_id = await persist_integration_sync_log_isolated(
            provider="whatapi",
            api_url=url.split("?")[0],
            engagement_id=engagement_id,
            user_id=user_id,
            request_payload={"name": name},
        )
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    url,
                    headers=self._auth_headers(include_api_key=True),
                )
            try:
                data = resp.json()
            except Exception:
                data = {"status_code": resp.status_code, "body": resp.text}
            if resp.status_code >= 400:
                await finalize_integration_sync_log_isolated(
                    sync_log_id=sync_log_id,
                    status="failed",
                    response_payload=data if isinstance(data, dict) else {"body": data},
                    error_message=resp.text[:500],
                )
                logger.error("WhatAPI template GET failed: %s %s", resp.status_code, resp.text[:500])
                raise AppError(
                    status_code=502,
                    error_code="EXTERNAL_SERVICE_ERROR",
                    message=f"Failed to fetch template '{name}'",
                )
            template: dict[str, Any] | None = None
            if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                items = data["data"]
                if items:
                    template = items[0]
            elif isinstance(data, dict) and data.get("name"):
                template = data
            if template is None:
                await finalize_integration_sync_log_isolated(
                    sync_log_id=sync_log_id,
                    status="failed",
                    response_payload=data if isinstance(data, dict) else {"body": data},
                    error_message=f"Template '{name}' not found",
                )
                raise AppError(
                    status_code=404,
                    error_code="NOT_FOUND",
                    message=f"Template '{name}' not found",
                )
            await finalize_integration_sync_log_isolated(
                sync_log_id=sync_log_id,
                status="success",
                response_payload=template,
            )
            return template
        except AppError:
            raise
        except Exception as exc:
            await finalize_integration_sync_log_isolated(
                sync_log_id=sync_log_id,
                status="failed",
                error_message=str(exc),
            )
            raise AppError(
                status_code=503,
                error_code="EXTERNAL_SERVICE_UNAVAILABLE",
                message="WhatAPI request failed",
            ) from exc

    async def send_template_message(
        self,
        *,
        to: str,
        template_name: str,
        language_code: str,
        components: list[dict[str, Any]],
        engagement_id: int | None = None,
        user_id: int | None = None,
    ) -> WhatApiSendResult:
        if not self._api_base or not settings.WHATAPI_PHONE_NUMBER_ID:
            raise AppError(
                status_code=503,
                error_code="EXTERNAL_SERVICE_UNAVAILABLE",
                message="WhatAPI is not configured",
            )

        phone = normalize_whatsapp_phone(to)
        url = f"{self._api_base}{settings.WHATAPI_PHONE_NUMBER_ID}/messages"
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"policy": "deterministic", "code": language_code},
                "components": components,
            },
        }

        sync_log_id = await persist_integration_sync_log_isolated(
            provider="whatapi",
            api_url=url,
            engagement_id=engagement_id,
            user_id=user_id,
            request_payload=body,
        )

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=body, headers=self._auth_headers())
            resp_data: dict[str, Any]
            try:
                resp_data = resp.json()
            except Exception:
                resp_data = {"status_code": resp.status_code, "body": resp.text}

            if resp.status_code >= 400:
                await finalize_integration_sync_log_isolated(
                    sync_log_id=sync_log_id,
                    status="failed",
                    response_payload=resp_data,
                    error_message=resp.text[:500],
                )
                raise AppError(
                    status_code=502,
                    error_code="EXTERNAL_SERVICE_ERROR",
                    message="WhatAPI rejected template send",
                )

            message_obj = resp_data.get("message") if isinstance(resp_data, dict) else None
            queue_id = None
            message_status = None
            if isinstance(message_obj, dict):
                queue_id = message_obj.get("queue_id") or message_obj.get("id")
                message_status = message_obj.get("message_status") or message_obj.get("status")

            await finalize_integration_sync_log_isolated(
                sync_log_id=sync_log_id,
                status="success",
                response_payload=resp_data if isinstance(resp_data, dict) else {"body": resp_data},
            )
            return WhatApiSendResult(
                queue_id=str(queue_id) if queue_id else None,
                message_status=str(message_status) if message_status else None,
                raw=resp_data if isinstance(resp_data, dict) else {"body": resp_data},
            )
        except AppError:
            raise
        except Exception as exc:
            await finalize_integration_sync_log_isolated(
                sync_log_id=sync_log_id,
                status="failed",
                error_message=str(exc),
            )
            raise AppError(
                status_code=503,
                error_code="EXTERNAL_SERVICE_UNAVAILABLE",
                message="WhatAPI request failed",
            ) from exc
