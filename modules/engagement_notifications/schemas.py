"""Pydantic schemas for engagement notifications API."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from common.validation import PositiveIntId

from modules.engagement_notifications.service_config import (
    NotificationServiceConfigItem,
    configs_to_api,
    normalize_notification_services,
    serialize_for_db,
)


class EngagementNotificationItem(BaseModel):
    event_code: str = Field(min_length=1)
    recipient_type: str | None = None
    notification_services: list[NotificationServiceConfigItem] = Field(default_factory=list)

    @field_validator("notification_services", mode="before")
    @classmethod
    def normalize_services(cls, value: object) -> list[NotificationServiceConfigItem]:
        return normalize_notification_services(value if isinstance(value, list) else [])


class EngagementNotificationResponse(BaseModel):
    id: int
    engagement_id: int
    event_code: str
    recipient_type: str
    notification_services: list[NotificationServiceConfigItem]
    event_display_name: str | None = None

    @field_validator("notification_services", mode="before")
    @classmethod
    def normalize_services(cls, value: object) -> list[NotificationServiceConfigItem]:
        return normalize_notification_services(value if isinstance(value, list) else [])


class EngagementNotificationsUpsertRequest(BaseModel):
    notifications: list[EngagementNotificationItem] = Field(default_factory=list)


class EffectiveEngagementNotificationResponse(BaseModel):
    engagement_id: int
    event_code: str
    recipient_type: str
    notification_services: list[NotificationServiceConfigItem]
    source: str
    event_display_name: str | None = None
    engagement_notification_id: int | None = None

    @field_validator("notification_services", mode="before")
    @classmethod
    def normalize_services(cls, value: object) -> list[NotificationServiceConfigItem]:
        return normalize_notification_services(value if isinstance(value, list) else [])


__all__ = [
    "EngagementNotificationItem",
    "EngagementNotificationResponse",
    "EngagementNotificationsUpsertRequest",
    "EffectiveEngagementNotificationResponse",
    "NotificationServiceConfigItem",
    "configs_to_api",
    "normalize_notification_services",
    "serialize_for_db",
]
