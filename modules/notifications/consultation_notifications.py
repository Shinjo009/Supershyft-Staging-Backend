"""Dispatch consultation readiness notifications for home-collection consultation engagements."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from modules.engagements.repository import EngagementsRepository
from modules.notifications.engine import emit_notification_event
from modules.notifications.service import NotificationsService

logger = logging.getLogger(__name__)

_IST = ZoneInfo("Asia/Kolkata")


async def dispatch_consultation_notifications(
    db: AsyncSession,
    *,
    notifications_service: NotificationsService,
    engagements_repository: EngagementsRepository,
    as_of: date | None = None,
    dry_run: bool = False,
) -> dict[str, int | str | bool | list[dict[str, Any]]]:
    """Notify participants whose blood test report is ready for consultation booking."""
    participants = await engagements_repository.list_participants_for_consultation_notification(db)

    matched = len(participants)
    sent = 0
    skipped = 0
    failed = 0
    details: list[dict[str, Any]] = []
    reference_date = (as_of or datetime.now(_IST).date()).isoformat()

    if dry_run:
        for user_id, engagement_id, service_configs in participants:
            service_keys = [cfg.service_key for cfg in service_configs]
            details.append({
                "user_id": user_id,
                "engagement_id": engagement_id,
                "service_key": ",".join(service_keys) if service_keys else None,
                "action": "dry_run",
                "reason": "no notification keys configured" if not service_keys else "would dispatch",
            })
        return {
            "as_of": reference_date,
            "matched": matched,
            "sent": 0,
            "skipped": matched,
            "failed": 0,
            "dry_run": True,
            "details": details,
        }

    for user_id, engagement_id, service_configs in participants:
        service_keys = [cfg.service_key for cfg in service_configs]
        if not service_configs:
            skipped += 1
            details.append({
                "user_id": user_id,
                "engagement_id": engagement_id,
                "action": "skipped",
                "reason": "no notification keys configured",
            })
            continue

        try:
            ids = await emit_notification_event(
                db,
                "consultation_ready",
                {"user_id": user_id},
                engagement_id=engagement_id,
                notifications_service=notifications_service,
            )
            if ids:
                sent += 1
                details.append({
                    "user_id": user_id,
                    "engagement_id": engagement_id,
                    "action": "sent",
                    "reason": "dispatched consultation_ready",
                })
            else:
                skipped += 1
                details.append({
                    "user_id": user_id,
                    "engagement_id": engagement_id,
                    "action": "skipped",
                    "reason": "no bindings or deduped",
                })
        except Exception as exc:
            failed += 1
            details.append({
                "user_id": user_id,
                "engagement_id": engagement_id,
                "service_key": ",".join(service_keys),
                "action": "failed",
                "reason": str(exc),
            })
            logger.warning(
                "Consultation notification dispatch failed: service_keys=%s user_id=%s engagement_id=%s: %s",
                ",".join(service_keys),
                user_id,
                engagement_id,
                str(exc),
            )

    return {
        "as_of": reference_date,
        "matched": matched,
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
        "dry_run": False,
        "details": details,
    }
