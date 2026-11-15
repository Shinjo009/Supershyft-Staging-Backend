"""Backfill users.created_at from Metsights profile detail (GET /external/profiles/:id/)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.metsights.service import MetsightsService
from modules.users.models import User
from modules.users.repository import UsersRepository

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, int, int, int], None]


def _parse_metsights_timestamp(raw: Any) -> datetime | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def backfill_users_created_at_from_metsights(
    db: AsyncSession,
    *,
    metsights_service: MetsightsService,
    users_repo: UsersRepository | None = None,
    user_id: int | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    sleep_ms: int = 50,
    batch_size: int = 25,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Fetch profile created_at from MetSights and write users.created_at when NULL."""

    repo = users_repo or UsersRepository()
    candidates = await repo.list_users_for_created_at_backfill(
        db,
        user_id=user_id,
        limit=limit,
    )
    total = len(candidates)
    updated = 0
    skipped = 0
    failed = 0
    details: list[dict[str, Any]] = []
    pending_writes = 0

    def _report(done: int) -> None:
        if on_progress is not None:
            on_progress(done, total, updated, skipped, failed)

    _report(0)
    sleep_sec = max(0, sleep_ms) / 1000.0
    batch_size = max(1, batch_size)

    for index, (uid, profile_id) in enumerate(candidates, start=1):
        if sleep_sec > 0 and index > 1:
            await asyncio.sleep(sleep_sec)

        try:
            profile_data = await metsights_service.get_profile_detail(profile_id=profile_id)
            if not isinstance(profile_data, dict):
                raise ValueError(f"unexpected profile detail type: {type(profile_data)!r}")

            remote_created_at = _parse_metsights_timestamp(profile_data.get("created_at"))
            if remote_created_at is None:
                skipped += 1
                details.append(
                    {
                        "user_id": uid,
                        "metsights_profile_id": profile_id,
                        "action": "skipped",
                        "reason": "missing created_at on Metsights profile",
                    }
                )
                _report(index)
                continue

            row = await db.scalar(select(User).where(User.user_id == uid))
            if row is None:
                skipped += 1
                details.append(
                    {
                        "user_id": uid,
                        "metsights_profile_id": profile_id,
                        "action": "skipped",
                        "reason": "user not found",
                    }
                )
                _report(index)
                continue

            if row.created_at is not None:
                skipped += 1
                details.append(
                    {
                        "user_id": uid,
                        "metsights_profile_id": profile_id,
                        "action": "skipped",
                        "reason": "created_at already set",
                    }
                )
                _report(index)
                continue

            reason = f"set created_at={remote_created_at.isoformat()}"
            if dry_run:
                updated += 1
                details.append(
                    {
                        "user_id": uid,
                        "metsights_profile_id": profile_id,
                        "action": "would_update",
                        "reason": f"dry-run: {reason}",
                    }
                )
                _report(index)
                continue

            row.created_at = remote_created_at
            pending_writes += 1
            updated += 1
            details.append(
                {
                    "user_id": uid,
                    "metsights_profile_id": profile_id,
                    "action": "updated",
                    "reason": reason,
                }
            )

            if pending_writes >= batch_size:
                await db.commit()
                pending_writes = 0
        except Exception as exc:
            if not dry_run:
                await db.rollback()
                pending_writes = 0
            failed += 1
            details.append(
                {
                    "user_id": uid,
                    "metsights_profile_id": profile_id,
                    "action": "failed",
                    "reason": str(exc),
                }
            )
            logger.warning(
                "backfill_users_created_at failed: user_id=%s profile=%s: %s",
                uid,
                profile_id,
                exc,
                exc_info=True,
            )

        _report(index)

    if not dry_run and pending_writes > 0:
        await db.commit()

    return {
        "matched": total,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "dry_run": dry_run,
        "user_id": user_id,
        "limit": limit,
        "details": details,
    }