"""Engagement notifications repository."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.engagement_notifications.service_config import (
    extract_service_keys,
    prepare_notification_items_for_storage,
)
from modules.engagements.models import EngagementNotification


class EngagementNotificationsRepository:
    """Database queries for engagement_notifications."""

    async def list_for_engagement(
        self,
        db: AsyncSession,
        engagement_id: int,
    ) -> list[EngagementNotification]:
        query = (
            select(EngagementNotification)
            .where(EngagementNotification.engagement_id == engagement_id)
            .order_by(EngagementNotification.event_code.asc())
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_for_engagement_and_event_code(
        self,
        db: AsyncSession,
        *,
        engagement_id: int,
        event_code: str,
    ) -> EngagementNotification | None:
        query = (
            select(EngagementNotification)
            .where(EngagementNotification.engagement_id == engagement_id)
            .where(EngagementNotification.event_code == event_code)
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def get_services_for_engagement_event(
        self,
        db: AsyncSession,
        *,
        engagement_id: int,
        event_code: str,
    ) -> list[str]:
        en = await self.get_for_engagement_and_event_code(
            db, engagement_id=engagement_id, event_code=event_code
        )
        if en is None:
            return []
        return extract_service_keys(en.notification_services)

    async def upsert_for_engagement(
        self,
        db: AsyncSession,
        engagement_id: int,
        notifications: list[dict],
    ) -> list[EngagementNotification]:
        prepared = await prepare_notification_items_for_storage(db, notifications)

        await db.execute(
            delete(EngagementNotification).where(
                EngagementNotification.engagement_id == engagement_id
            )
        )
        result = []
        for item in prepared:
            obj = EngagementNotification(
                engagement_id=engagement_id,
                notification_services=item["notification_services"],
                event_code=item["event_code"],
                recipient_type=item["recipient_type"],
            )
            db.add(obj)
            result.append(obj)
        await db.flush()
        return result

    async def populate_from_defaults(
        self,
        db: AsyncSession,
        *,
        engagement_id: int,
        engagement_type_id: int,
    ) -> list[EngagementNotification]:
        """Legacy per-type defaults removed at cutover; use global bindings + wizard."""
        _ = engagement_id, engagement_type_id
        return []
