"""Dispatch report-ready notification services via the event engine."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.engagement_notifications.service_config import NotificationServiceConfigItem
from modules.notifications.engine import emit_notification_event
from modules.notifications.service import NotificationsService
from modules.reports.blood_booking_reports import has_archived_diagnostic_blood_report


async def send_report_notifications(
    db: AsyncSession,
    *,
    notifications_service: NotificationsService,
    service_configs: list[NotificationServiceConfigItem] | None = None,
    user_id: int,
    engagement_id: int,
    assessment_instance_id: int,
    details: list[dict[str, Any]],
    event_code: str = "blood_report_ready",
    repository=None,
) -> int:
    """Emit a report-ready event; commits are handled by the caller when needed."""
    _ = service_configs, repository

    if event_code == "blood_report_ready":
        has_archived_pdf = await has_archived_diagnostic_blood_report(
            db,
            user_id=user_id,
            engagement_id=engagement_id,
        )
        if not has_archived_pdf:
            details.append({
                "user_id": user_id,
                "engagement_id": engagement_id,
                "action": "skipped",
                "reason": f"Blood report URL not available for user_id={user_id}",
            })
            return 0

    try:
        notification_ids = await emit_notification_event(
            db,
            event_code,
            {
                "user_id": user_id,
                "assessment_instance_id": assessment_instance_id,
            },
            engagement_id=engagement_id,
            notifications_service=notifications_service,
        )
    except Exception as exc:
        details.append({
            "user_id": user_id,
            "engagement_id": engagement_id,
            "action": "skipped",
            "reason": str(exc)[:200],
        })
        return 0

    if not notification_ids:
        details.append({
            "user_id": user_id,
            "engagement_id": engagement_id,
            "action": "skipped",
            "reason": "no notification bindings or all deduped",
        })
        return 0

    for _ in notification_ids:
        details.append({
            "user_id": user_id,
            "engagement_id": engagement_id,
            "action": "notified",
            "reason": f"dispatched '{event_code}'",
        })
    return len(notification_ids)
