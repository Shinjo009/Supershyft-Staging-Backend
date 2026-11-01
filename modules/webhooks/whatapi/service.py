"""WhatAPI delivery webhook handling."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppError
from modules.audit.cron_sync_logging import (
    finalize_integration_sync_log_isolated,
    persist_integration_sync_log_isolated,
)
from modules.notifications.repository import NotificationsRepository

logger = logging.getLogger(__name__)

_WHATAPI_TO_NOTIFICATION_STATUS = {
    "queued": "queued",
    "sent": "sent",
    "delivered": "delivered",
    "read": "read",
    "failed": "failed",
    "error": "failed",
}

_PROGRESSION_ORDER = {
    "queued": 0,
    "sent": 1,
    "delivered": 2,
    "read": 3,
}


def extract_queue_id_from_webhook(payload: dict[str, Any]) -> str | None:
    message = payload.get("message")
    if isinstance(message, dict):
        qid = message.get("queue_id")
        if qid:
            return str(qid)
    qid = payload.get("queue_id")
    return str(qid) if qid else None


def extract_provider_status(payload: dict[str, Any]) -> str:
    message = payload.get("message")
    if isinstance(message, dict):
        for key in ("message_status", "status"):
            val = message.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip().lower()
    for key in ("message_status", "status"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().lower()
    return ""


def map_whatapi_status(provider_status: str) -> str | None:
    return _WHATAPI_TO_NOTIFICATION_STATUS.get(provider_status.lower())


def _failure_message(payload: dict[str, Any]) -> str | None:
    for key in ("error", "error_message", "reason", "message"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip() and key != "message":
            return val.strip()
    message = payload.get("message")
    if isinstance(message, dict):
        for key in ("error", "error_message", "reason"):
            val = message.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


class WhatapiWebhookService:
    def __init__(self, *, repository: NotificationsRepository | None = None) -> None:
        self._repo = repository or NotificationsRepository()

    async def handle_delivery_webhook(
        self,
        db: AsyncSession,
        *,
        payload: dict[str, Any],
        api_endpoint_url: str,
    ) -> dict:
        sync_log_id = await persist_integration_sync_log_isolated(
            provider="whatapi",
            api_url=api_endpoint_url,
            request_payload=payload,
        )

        queue_id = extract_queue_id_from_webhook(payload)
        if not queue_id:
            await finalize_integration_sync_log_isolated(
                sync_log_id=sync_log_id,
                status="failed",
                error_message="Missing queue_id in webhook payload",
            )
            raise AppError(
                status_code=400,
                error_code="INVALID_INPUT",
                message="Missing queue_id in webhook payload",
            )

        provider_status = extract_provider_status(payload)
        mapped = map_whatapi_status(provider_status)
        if not mapped:
            await finalize_integration_sync_log_isolated(
                sync_log_id=sync_log_id,
                status="failed",
                error_message=f"Unsupported provider status: {provider_status!r}",
            )
            raise AppError(
                status_code=400,
                error_code="INVALID_INPUT",
                message=f"Unsupported delivery status: {provider_status!r}",
            )

        notification = await self._repo.get_notification_by_queue_id(db, queue_id=queue_id)
        if notification is None:
            await finalize_integration_sync_log_isolated(
                sync_log_id=sync_log_id,
                status="failed",
                error_message=f"No notification for queue_id={queue_id}",
            )
            raise AppError(
                status_code=404,
                error_code="NOT_FOUND",
                message=f"Notification not found for queue_id={queue_id}",
            )

        current = notification.status
        if current == "failed" and mapped != "failed":
            await finalize_integration_sync_log_isolated(
                sync_log_id=sync_log_id,
                status="failed",
                error_message=f"Cannot move from failed to {mapped}",
            )
            raise AppError(
                status_code=400,
                error_code="INVALID_STATE",
                message=f"Cannot update notification from status '{current}'",
            )

        if current in _PROGRESSION_ORDER and mapped in _PROGRESSION_ORDER:
            if _PROGRESSION_ORDER[mapped] < _PROGRESSION_ORDER.get(current, -1):
                await finalize_integration_sync_log_isolated(
                    sync_log_id=sync_log_id,
                    status="success",
                    response_payload={"skipped": True, "reason": "status regression ignored"},
                )
                return {
                    "notification_id": notification.notification_id,
                    "status": current,
                    "skipped": True,
                }

        values: dict[str, Any] = {"status": mapped}
        if mapped == "failed":
            fail_msg = _failure_message(payload) or f"WhatAPI delivery failed ({provider_status})"
            values["message"] = fail_msg
        elif provider_status:
            values["message"] = f"WhatAPI status: {provider_status}"

        if mapped in ("sent", "delivered", "read"):
            values["completed_at"] = datetime.now(timezone.utc)

        await self._repo.update_notification(
            db,
            notification_id=notification.notification_id,
            values=values,
        )
        await finalize_integration_sync_log_isolated(
            sync_log_id=sync_log_id,
            status="success",
            response_payload={
                "notification_id": notification.notification_id,
                "status": mapped,
            },
        )
        return {
            "notification_id": notification.notification_id,
            "status": mapped,
        }
