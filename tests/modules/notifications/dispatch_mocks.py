"""Shared mocks for notification dispatch tests (direct WhatAPI/SMTP path)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from modules.notifications.direct_dispatch import DeliverResult, DirectNotificationDispatch


def patch_direct_deliver_batch(
    monkeypatch: Any,
    deliver_calls: list[dict[str, Any]],
    *,
    succeed: bool = True,
    status: str = "sent",
    message: str = "ok",
) -> None:
    """Record kwargs passed to DirectNotificationDispatch.deliver_batch and return a stub result."""

    async def _deliver(self, **kwargs: Any) -> DeliverResult:
        deliver_calls.append(kwargs)
        completed = datetime.now(timezone.utc)
        if not succeed:
            return DeliverResult(
                status="failed",
                message=message or "delivery failed",
                completed_at=completed,
            )
        return DeliverResult(
            status=status,
            message=message,
            completed_at=completed,
        )

    monkeypatch.setattr(DirectNotificationDispatch, "deliver_batch", _deliver)


def patch_service_direct_deliver(
    monkeypatch: Any,
    deliver_calls: list[dict[str, Any]],
    *,
    succeed: bool = True,
    status: str = "sent",
    message: str = "ok",
) -> None:
    """Patch deliver_batch on the class used by NotificationsService."""
    patch_direct_deliver_batch(
        monkeypatch, deliver_calls, succeed=succeed, status=status, message=message
    )