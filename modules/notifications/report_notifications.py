"""Dispatch report-ready notification services without cross-service transaction rollback."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppError
from modules.notifications.models import NotificationService
from modules.engagement_notifications.service_config import NotificationServiceConfigItem
from modules.notifications.dedup import should_skip_notification
from modules.notifications.repository import NotificationsRepository
from modules.notifications.schemas import DispatchRequest
from modules.notifications.service import NotificationsService
from modules.reports.blood_booking_reports import has_archived_diagnostic_blood_report


async def send_report_notifications(
    db: AsyncSession,
    *,
    notifications_service: NotificationsService,
    service_configs: list[NotificationServiceConfigItem],
    user_id: int,
    engagement_id: int,
    assessment_instance_id: int,
    details: list[dict[str, Any]],
    repository: NotificationsRepository | None = None,
) -> int:
    """Dispatch configured notification services that have not already been sent.

    Commits after each successful dispatch so a later service failure does not
    roll back earlier notifications (integration_sync_logs are already isolated).
    """
    repo = repository or NotificationsRepository()
    sent_count = 0
    service_cache: dict[str, NotificationService | None] = {}
    needs_blood_check = False

    for cfg in service_configs:
        sk = cfg.service_key
        if sk not in service_cache:
            service_cache[sk] = await repo.get_service_by_key(db, service_key=sk)
        svc = service_cache[sk]
        if svc is not None and svc.require_blood_report_url:
            needs_blood_check = True

    has_archived_pdf: bool | None = None
    if needs_blood_check:
        has_archived_pdf = await has_archived_diagnostic_blood_report(
            db,
            user_id=user_id,
            engagement_id=engagement_id,
        )

    for cfg in service_configs:
        sk = cfg.service_key
        skip_reason = await should_skip_notification(
            db,
            service_key=sk,
            user_id=user_id,
            engagement_id=engagement_id,
            repository=repo,
        )
        if skip_reason:
            details.append({
                "user_id": user_id,
                "engagement_id": engagement_id,
                "action": "skipped",
                "reason": f"notification '{sk}' {skip_reason}",
            })
            continue

        svc = service_cache.get(sk)
        if svc is not None and svc.require_blood_report_url:
            if not has_archived_pdf:
                details.append({
                    "user_id": user_id,
                    "engagement_id": engagement_id,
                    "action": "skipped",
                    "reason": f"Blood report URL not available for user_id={user_id}",
                })
                continue

        try:
            await notifications_service.dispatch(
                db,
                payload=DispatchRequest(
                    service_key=sk,
                    user_ids=[user_id],
                    engagement_id=engagement_id,
                    assessment_instance_id=assessment_instance_id,
                    external_link=cfg.external_link,
                ),
                triggered_by_user_id=None,
            )
        except AppError as exc:
            details.append({
                "user_id": user_id,
                "engagement_id": engagement_id,
                "action": "skipped",
                "reason": str(exc)[:200],
            })
            continue

        await db.commit()
        sent_count += 1
        details.append({
            "user_id": user_id,
            "engagement_id": engagement_id,
            "action": "notified",
            "reason": f"dispatched '{sk}'",
        })

    return sent_count
