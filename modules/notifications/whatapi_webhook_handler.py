"""Process WhatAPI/Meta delivery status webhook payloads."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from modules.notifications.context_builder import normalize_whatsapp_phone
from modules.notifications.repository import NotificationsRepository

logger = logging.getLogger(__name__)

_TERMINAL_SENT = frozenset({"sent", "delivered", "read", "played"})
_TERMINAL_FAILED = frozenset({"failed", "undelivered", "rejected"})
_META_DELIVERED = frozenset({"delivered", "read", "played"})
_RECIPIENT_MATCH_HOURS = 48


@dataclass(frozen=True)
class WebhookStatusEvent:
    source: Literal["whatapi", "meta"]
    status: str
    detail: str | None
    queue_id: str | None = None
    wamid: str | None = None
    recipient_id: str | None = None


def _normalize_status(raw: str | None) -> str | None:
    if raw is None:
        return None
    normalized = str(raw).strip().lower()
    return normalized or None


def _normalize_digits(value: str | None) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _error_detail_from_node(node: dict[str, Any]) -> str | None:
    errors = node.get("errors")
    if isinstance(errors, list) and errors:
        parts: list[str] = []
        for item in errors:
            if not isinstance(item, dict):
                continue
            title = (
                item.get("title")
                or item.get("message")
                or item.get("error_data", {}).get("details")
            )
            if title:
                parts.append(str(title).strip())
        if parts:
            return "; ".join(parts)
    for key in ("error_message", "reason", "detail", "title"):
        val = node.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _db_status_for_whatapi_queue(status: str) -> str | None:
    if status in ("queued", "pending", "accepted"):
        return "pending"
    if status in _TERMINAL_SENT:
        return "sent"
    if status in _TERMINAL_FAILED:
        return "failed"
    return None


def _db_status_for_meta(status: str) -> tuple[str | None, bool]:
    """Return (db_status, set_completed_at)."""
    if status == "sent":
        return "pending", False
    if status in _META_DELIVERED:
        return "sent", True
    if status in _TERMINAL_FAILED:
        return "failed", True
    if status in ("queued", "pending", "accepted"):
        return "pending", False
    return None, False


def _db_status_for_event(event: WebhookStatusEvent) -> tuple[str | None, bool]:
    status = _normalize_status(event.status)
    if status is None:
        return None, False
    if event.source == "meta":
        return _db_status_for_meta(status)
    return _db_status_for_whatapi_queue(status), status in (
        _TERMINAL_SENT | _TERMINAL_FAILED
    )


def _status_rank(db_status: str) -> int:
    if db_status == "failed":
        return 3
    if db_status == "sent":
        return 2
    return 1


def _extract_whatapi_queue_events(obj: Any) -> list[WebhookStatusEvent]:
    found: list[WebhookStatusEvent] = []

    def record(queue_id: str, status_raw: Any, detail: str | None, source: dict[str, Any]) -> None:
        status = _normalize_status(status_raw if isinstance(status_raw, str) else None)
        if not status:
            return
        merged_detail = detail or _error_detail_from_node(source)
        found.append(
            WebhookStatusEvent(
                source="whatapi",
                status=status,
                detail=merged_detail,
                queue_id=queue_id.strip(),
            )
        )

    def visit(node: Any, meta_queue_id: str | None = None) -> None:
        if isinstance(node, dict):
            queue_id = node.get("queue_id") or node.get("queueId")
            if isinstance(queue_id, str) and queue_id.strip():
                meta_queue_id = queue_id.strip()
            status_raw = (
                node.get("message_status")
                or node.get("messageStatus")
                or node.get("status")
            )
            if isinstance(meta_queue_id, str) and meta_queue_id:
                if isinstance(status_raw, str) and _normalize_status(status_raw):
                    if "statuses" not in node:
                        record(
                            meta_queue_id,
                            status_raw,
                            _error_detail_from_node(node),
                            node,
                        )

            statuses = node.get("statuses")
            if isinstance(statuses, list) and isinstance(meta_queue_id, str):
                for st in statuses:
                    if not isinstance(st, dict):
                        continue
                    wamid = st.get("id")
                    if isinstance(wamid, str) and wamid.strip().lower().startswith("wamid."):
                        continue
                    record(
                        meta_queue_id,
                        st.get("status"),
                        _error_detail_from_node(st),
                        st,
                    )

            for value in node.values():
                visit(value, meta_queue_id)
        elif isinstance(node, list):
            for item in node:
                visit(item, meta_queue_id)

    visit(obj)
    return found


def _extract_meta_status_events(obj: Any) -> list[WebhookStatusEvent]:
    found: list[WebhookStatusEvent] = []

    def visit(node: Any, *, in_meta_value: bool = False) -> None:
        if isinstance(node, dict):
            next_in_meta = in_meta_value
            if node.get("object") == "whatsapp_business_account":
                next_in_meta = True
            if str(node.get("messaging_product") or "").strip().lower() == "whatsapp":
                next_in_meta = True

            statuses = node.get("statuses")
            if isinstance(statuses, list) and next_in_meta:
                for st in statuses:
                    if not isinstance(st, dict):
                        continue
                    wamid = st.get("id")
                    if not isinstance(wamid, str) or not wamid.strip().lower().startswith(
                        "wamid."
                    ):
                        continue
                    status = _normalize_status(
                        st.get("status") if isinstance(st.get("status"), str) else None
                    )
                    if not status:
                        continue
                    recipient = st.get("recipient_id")
                    recipient_id = (
                        str(recipient).strip()
                        if isinstance(recipient, str) and recipient.strip()
                        else None
                    )
                    found.append(
                        WebhookStatusEvent(
                            source="meta",
                            status=status,
                            detail=_error_detail_from_node(st),
                            wamid=wamid.strip(),
                            recipient_id=recipient_id,
                        )
                    )

            for value in node.values():
                visit(value, in_meta_value=next_in_meta)
        elif isinstance(node, list):
            for item in node:
                visit(item, in_meta_value=in_meta_value)

    visit(obj)
    return found


def extract_status_events(obj: Any) -> list[WebhookStatusEvent]:
    """Extract delivery status events from WhatAPI or Meta webhook JSON."""
    return _extract_whatapi_queue_events(obj) + _extract_meta_status_events(obj)


def _walk_for_queue_status(obj: Any) -> list[tuple[str, str, str | None]]:
    """Legacy tuple format for unit tests (queue_id events only)."""
    pairs: list[tuple[str, str, str | None]] = []
    for event in _extract_whatapi_queue_events(obj):
        if event.queue_id:
            pairs.append((event.queue_id, event.status, event.detail))
    return pairs


def _delivery_message(whatapi_status: str, detail: str | None) -> str | None:
    status = _normalize_status(whatapi_status)
    if status is None:
        return None
    if status in _TERMINAL_SENT or status in _META_DELIVERED:
        return f"WhatsApp delivered ({status})"
    if status in _TERMINAL_FAILED:
        base = f"WhatsApp delivery failed ({status})"
        if detail:
            return f"{base}: {detail}"
        return base
    if status == "sent":
        return "WhatsApp accepted by provider (awaiting delivery confirmation)"
    return None


class WhatApiWebhookHandler:
    def __init__(self, repo: NotificationsRepository | None = None) -> None:
        self._repo = repo or NotificationsRepository()

    async def _resolve_notification(
        self,
        db: AsyncSession,
        *,
        event: WebhookStatusEvent,
    ):
        if event.queue_id:
            row = await self._repo.get_notification_by_queue_id(db, queue_id=event.queue_id)
            if row is not None:
                return row

        if event.wamid:
            row = await self._repo.get_notification_by_whatsapp_message_id(
                db, whatsapp_message_id=event.wamid
            )
            if row is not None:
                return row

        recipient_digits = _normalize_digits(event.recipient_id)
        if recipient_digits:
            since = datetime.now(timezone.utc) - timedelta(hours=_RECIPIENT_MATCH_HOURS)
            row = await self._repo.find_recent_whatsapp_notification_by_recipient(
                db,
                recipient_digits=recipient_digits,
                dispatched_after=since,
            )
            if row is not None:
                return row

        return None

    async def handle_status_payload(
        self, db: AsyncSession, *, payload: dict[str, Any] | list[Any]
    ) -> dict[str, Any]:
        events = extract_status_events(payload)
        if not events:
            logger.info("WhatAPI webhook: no status events in payload")
            return {"updated": 0, "ignored": True}

        now = datetime.now(timezone.utc)
        pending_by_id: dict[int, dict[str, Any]] = {}

        for event in events:
            db_status, set_completed = _db_status_for_event(event)
            if db_status is None:
                logger.info(
                    "WhatAPI webhook: ignoring status %s source=%s",
                    event.status,
                    event.source,
                )
                continue

            notification = await self._resolve_notification(db, event=event)
            if notification is None:
                logger.info(
                    "WhatAPI webhook: no notification for event queue_id=%s wamid=%s recipient=%s",
                    event.queue_id,
                    event.wamid,
                    event.recipient_id,
                )
                continue

            nid = int(notification.notification_id)
            values: dict[str, Any] = {"status": db_status}
            if event.wamid:
                values["whatsapp_message_id"] = event.wamid

            msg = _delivery_message(event.status, event.detail)
            if msg and db_status in ("sent", "failed", "pending"):
                if db_status != "pending" or event.source == "meta":
                    values["message"] = msg
            elif event.detail and db_status == "failed":
                values["message"] = f"WhatsApp delivery failed: {event.detail}"

            if set_completed and db_status in ("sent", "failed"):
                values["completed_at"] = now

            existing = pending_by_id.get(nid)
            if existing is None or _status_rank(db_status) >= _status_rank(
                str(existing.get("status") or "pending")
            ):
                if existing:
                    existing.update(values)
                else:
                    pending_by_id[nid] = values

        updated = 0
        for notification_id, values in pending_by_id.items():
            await self._repo.update_notification(
                db,
                notification_id=notification_id,
                values=values,
            )
            updated += 1

        return {"updated": updated}
