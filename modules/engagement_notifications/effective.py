"""Effective notification bindings for an engagement (global defaults + overrides)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from modules.engagement_notifications.repository import EngagementNotificationsRepository
from modules.engagement_notifications.service_config import (
    NotificationServiceConfigItem,
    normalize_notification_services,
)
from modules.notifications.bindings_repository import NotificationEventBindingsRepository
from modules.notifications.events_catalog import get_event


@dataclass(frozen=True)
class EffectiveEngagementNotificationBinding:
    engagement_id: int
    event_code: str
    recipient_type: str
    notification_services: list[NotificationServiceConfigItem]
    source: str  # engagement | global
    event_display_name: str | None
    engagement_notification_id: int | None


def _display_name(event_code: str) -> str | None:
    catalog = get_event(event_code)
    return catalog.event_name if catalog else None


async def list_effective_for_engagement(
    db: AsyncSession,
    engagement_id: int,
    *,
    engagement_repo: EngagementNotificationsRepository | None = None,
    global_repo: NotificationEventBindingsRepository | None = None,
) -> list[EffectiveEngagementNotificationBinding]:
    """Merge global notification_events with engagement_notifications (engagement wins)."""
    eng_repo = engagement_repo or EngagementNotificationsRepository()
    global_repo = global_repo or NotificationEventBindingsRepository()

    by_key: dict[tuple[str, str], EffectiveEngagementNotificationBinding] = {}

    for en_row in await eng_repo.list_for_engagement(db, engagement_id):
        configs = normalize_notification_services(en_row.notification_services)
        if not configs:
            continue
        event_code = str(en_row.event_code)
        recipient_type = (en_row.recipient_type or "").strip() or "participant"
        by_key[(event_code, recipient_type)] = EffectiveEngagementNotificationBinding(
            engagement_id=engagement_id,
            event_code=event_code,
            recipient_type=recipient_type,
            notification_services=configs,
            source="engagement",
            event_display_name=_display_name(event_code),
            engagement_notification_id=int(en_row.id),
        )

    for row in await global_repo.list_all(db):
        if not row.is_active:
            continue
        configs = normalize_notification_services(row.notification_services)
        if not configs:
            continue
        event_code = str(row.event_code)
        recipient_type = str(row.recipient_type)
        key = (event_code, recipient_type)
        if key in by_key:
            continue
        by_key[key] = EffectiveEngagementNotificationBinding(
            engagement_id=engagement_id,
            event_code=event_code,
            recipient_type=recipient_type,
            notification_services=configs,
            source="global",
            event_display_name=_display_name(event_code) or row.event_name,
            engagement_notification_id=None,
        )

    return sorted(
        by_key.values(),
        key=lambda item: (item.event_code, item.recipient_type),
    )
