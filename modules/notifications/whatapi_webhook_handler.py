"""Parse inbound WhatAPI webhook payloads and update notifications."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.audit.cron_sync_logging import persist_integration_sync_log_isolated
from modules.notifications.repository import NotificationsRepository

logger = logging.getLogger(__name__)

_STATUS_MAP = {
    "sent": "sent",
    "delivered": "delivered",
    "read": "read",
    "failed": "failed",
    "deleted": "deleted",
    "queued": "queued",
}


def extract_queue_id(payload: dict[str, Any]) -> str | None:
    candidates = [
        payload.get("queue_id"),
        payload.get("message_id"),
    ]
    message = payload.get("message")
    if isinstance(message, dict):
        candidates.extend([
            message.get("queue_id"),
            message.get("id"),
        ])
    data = payload.get("data")
    if isinstance(data, dict):
        candidates.append(data.get("queue_id"))
    for value in candidates:
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def map_webhook_status(payload: dict[str, Any]) -> str | None:
    for key in ("status", "message_status", "event", "type"):
        raw = payload.get(key)
        if raw is None and isinstance(payload.get("message"), dict):
            raw = payload["message"].get(key)
        if raw is None:
            continue
        label = str(raw).lower().strip()
        if label in _STATUS_MAP:
            return _STATUS_MAP[label]
    return None


async def handle_whatapi_webhook_post(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    api_endpoint_url: str,
) -> dict[str, Any]:
    queue_id = extract_queue_id(payload)
    status = map_webhook_status(payload)

    await persist_integration_sync_log_isolated(
        provider="whatapi",
        api_url=api_endpoint_url,
        request_payload=payload,
        status="success" if queue_id else "skipped",
    )

    if not queue_id:
        return {"updated": False, "reason": "no_queue_id"}

    if status is None:
        return {"updated": False, "queue_id": queue_id, "reason": "unmapped_status"}

    repo = NotificationsRepository()
    notification = await repo.get_notification_by_queue_id(db, queue_id=queue_id)
    if notification is None:
        return {"updated": False, "queue_id": queue_id, "reason": "notification_not_found"}

    values: dict[str, Any] = {"status": status, "message": f"WhatAPI webhook: {status}"}
    if status in ("sent", "delivered", "read"):
        values["completed_at"] = datetime.now(timezone.utc)

    await repo.update_notification(db, notification_id=notification.notification_id, values=values)
    return {
        "updated": True,
        "notification_id": notification.notification_id,
        "queue_id": queue_id,
        "status": status,
    }
