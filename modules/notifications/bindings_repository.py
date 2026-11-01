"""Repository for global notification event bindings (notification_events table)."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.notifications.models import NotificationEventBinding


class NotificationEventBindingsRepository:
    async def list_all(self, db: AsyncSession) -> list[NotificationEventBinding]:
        result = await db.execute(
            select(NotificationEventBinding).order_by(
                NotificationEventBinding.event_code.asc(),
                NotificationEventBinding.recipient_type.asc(),
            )
        )
        return list(result.scalars().all())

    async def get_by_id(self, db: AsyncSession, binding_id: int) -> NotificationEventBinding | None:
        result = await db.execute(
            select(NotificationEventBinding).where(NotificationEventBinding.id == binding_id)
        )
        return result.scalar_one_or_none()

    async def get_by_code_and_recipient(
        self,
        db: AsyncSession,
        *,
        event_code: str,
        recipient_type: str,
    ) -> NotificationEventBinding | None:
        result = await db.execute(
            select(NotificationEventBinding).where(
                NotificationEventBinding.event_code == event_code,
                NotificationEventBinding.recipient_type == recipient_type,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        db: AsyncSession,
        *,
        event_code: str,
        event_name: str,
        recipient_type: str,
        notification_services: list[str],
        custom_contacts: dict | None,
        filters: dict | None,
        is_active: bool,
    ) -> NotificationEventBinding:
        obj = NotificationEventBinding(
            event_code=event_code,
            event_name=event_name,
            recipient_type=recipient_type,
            notification_services=notification_services,
            custom_contacts=custom_contacts,
            filters=filters,
            is_active=is_active,
        )
        db.add(obj)
        await db.flush()
        return obj

    async def update(
        self,
        db: AsyncSession,
        binding_id: int,
        *,
        event_name: str | None = None,
        notification_services: list[str] | None = None,
        custom_contacts: dict | None | object = ...,
        filters: dict | None | object = ...,
        is_active: bool | None = None,
    ) -> NotificationEventBinding | None:
        obj = await self.get_by_id(db, binding_id)
        if obj is None:
            return None
        if event_name is not None:
            obj.event_name = event_name
        if notification_services is not None:
            obj.notification_services = notification_services
        if custom_contacts is not ...:
            obj.custom_contacts = custom_contacts  # type: ignore[assignment]
        if filters is not ...:
            obj.filters = filters  # type: ignore[assignment]
        if is_active is not None:
            obj.is_active = is_active
        await db.flush()
        return obj

    async def delete(self, db: AsyncSession, binding_id: int) -> bool:
        result = await db.execute(
            delete(NotificationEventBinding).where(NotificationEventBinding.id == binding_id)
        )
        return result.rowcount > 0
