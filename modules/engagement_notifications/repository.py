"""Engagement notifications repository."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.engagement_notifications.service_config import (
    extract_service_keys,
    normalize_notification_services,
    prepare_notification_items_for_storage,
    serialize_for_db,
)
from modules.engagements.models import EngagementNotification, EngagementType
from modules.notifications.events_catalog import get_catalog_event
from modules.notifications.models import NotificationEvent

# Event codes applicable per engagement type (from legacy auto_notification_events seeds).
_EVENT_CODES_BY_ENGAGEMENT_TYPE: dict[str, tuple[str, ...]] = {
    "bio_ai": (
        "onboarding",
        "pretest_guidelines",
        "questionnaire_reminder_before",
        "questionnaire_reminder_after",
        "bioai_report_ready",
    ),
    "blood_test": (
        "onboarding",
        "pretest_guidelines",
        "questionnaire_reminder_before",
        "questionnaire_reminder_after",
        "blood_report_ready",
    ),
    "consultation": (
        "onboarding",
        "pretest_guidelines",
        "consultation_ready",
        "consultation_remainder",
        "consultation_booking_alert",
    ),
    "blood_test_with_consultation": (
        "onboarding",
        "pretest_guidelines",
        "questionnaire_reminder_before",
        "questionnaire_reminder_after",
        "blood_report_ready",
        "consultation_ready",
        "consultation_remainder",
        "consultation_booking_alert",
    ),
    "bio_ai_with_consultation": (
        "onboarding",
        "pretest_guidelines",
        "questionnaire_reminder_before",
        "questionnaire_reminder_after",
        "bioai_report_ready",
        "consultation_ready",
        "consultation_remainder",
        "consultation_booking_alert",
    ),
}


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
        recipient_type: str | None = None,
    ) -> EngagementNotification | None:
        query = (
            select(EngagementNotification)
            .where(EngagementNotification.engagement_id == engagement_id)
            .where(EngagementNotification.event_code == event_code)
        )
        if recipient_type is not None:
            query = query.where(EngagementNotification.recipient_type == recipient_type)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def list_for_engagement_and_event_code(
        self,
        db: AsyncSession,
        *,
        engagement_id: int,
        event_code: str,
    ) -> list[EngagementNotification]:
        query = (
            select(EngagementNotification)
            .where(EngagementNotification.engagement_id == engagement_id)
            .where(EngagementNotification.event_code == event_code)
            .order_by(EngagementNotification.recipient_type.asc())
        )
        result = await db.execute(query)
        return list(result.scalars().all())

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
                event_code=item["event_code"],
                recipient_type=item["recipient_type"],
                notification_services=item["notification_services"],
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
        type_row = await db.get(EngagementType, engagement_type_id)
        if type_row is None:
            return []
        type_code = type_row.code
        event_codes = _EVENT_CODES_BY_ENGAGEMENT_TYPE.get(type_code, ())
        if not event_codes:
            return []

        platform = await db.execute(
            select(NotificationEvent).where(NotificationEvent.event_code.in_(event_codes))
        )
        platform_rows = list(platform.scalars().all())

        items: list[dict] = []
        for binding in platform_rows:
            configs = normalize_notification_services(binding.notification_services)
            if not configs:
                continue
            items.append(
                {
                    "event_code": binding.event_code,
                    "recipient_type": binding.recipient_type,
                    "notification_services": serialize_for_db(configs),
                }
            )
        if not items:
            return []
        return await self.upsert_for_engagement(db, engagement_id, items)


async def list_default_bindings_for_engagement_type(
    db: AsyncSession,
    engagement_type_id: int,
) -> list[dict]:
    """Synthetic defaults: platform notification_events for this engagement type's event codes."""
    type_row = await db.get(EngagementType, engagement_type_id)
    if type_row is None:
        return []
    event_codes = _EVENT_CODES_BY_ENGAGEMENT_TYPE.get(type_row.code, ())
    if not event_codes:
        return []

    platform = await db.execute(
        select(NotificationEvent).where(NotificationEvent.event_code.in_(event_codes))
    )
    out: list[dict] = []
    for binding in platform.scalars().all():
        out.append(
            {
                "event_code": binding.event_code,
                "recipient_type": binding.recipient_type,
                "notification_services": binding.notification_services or [],
            }
        )
    return out
