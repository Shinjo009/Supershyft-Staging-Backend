"""Expire notifications stuck in pending without a callback."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from modules.notifications.repository import NotificationsRepository

DEFAULT_PENDING_TIMEOUT_HOURS = 2

_STALE_MESSAGE = (
    "Delivery timeout — WhatAPI webhook did not report completion"
)

_HEALED_MESSAGE = (
    "WhatsApp delivered (healed: completed_at was set before an out-of-order status webhook)"
)


async def expire_stale_notifications(
    db: AsyncSession,
    *,
    repository: NotificationsRepository | None = None,
    timeout_hours: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Mark pending notifications older than the timeout as failed.

    Rows that already have ``completed_at`` were delivered (or failed) and then
    incorrectly downgraded by an out-of-order webhook — heal those back to sent
    instead of timing them out as failed.
    """
    repo = repository or NotificationsRepository()
    hours = timeout_hours if timeout_hours is not None else DEFAULT_PENDING_TIMEOUT_HOURS
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    heal_ids = await repo.list_pending_completed_notification_ids(
        db, dispatched_before=cutoff
    )
    stale_ids = await repo.list_stale_pending_notification_ids(db, dispatched_before=cutoff)
    # Stale list includes heal candidates; exclude them from the fail path.
    heal_set = set(heal_ids)
    stale_ids = [nid for nid in stale_ids if nid not in heal_set]

    if dry_run:
        return {
            "timeout_hours": hours,
            "cutoff": cutoff.isoformat(),
            "expired": 0,
            "healed": 0,
            "would_expire": len(stale_ids),
            "would_heal": len(heal_ids),
            "notification_ids": stale_ids,
            "heal_notification_ids": heal_ids,
            "dry_run": True,
        }

    healed = await repo.heal_pending_completed_notifications(
        db,
        dispatched_before=cutoff,
        message=_HEALED_MESSAGE,
    )
    expired = await repo.expire_stale_pending_notifications(
        db,
        dispatched_before=cutoff,
        message=_STALE_MESSAGE,
    )
    return {
        "timeout_hours": hours,
        "cutoff": cutoff.isoformat(),
        "expired": expired,
        "healed": healed,
        "would_expire": len(stale_ids),
        "would_heal": len(heal_ids),
        "notification_ids": stale_ids,
        "heal_notification_ids": heal_ids,
        "dry_run": False,
    }
