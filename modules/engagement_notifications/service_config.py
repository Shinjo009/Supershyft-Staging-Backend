"""Helpers for per-service engagement notification configuration."""

from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppError
from modules.notifications.events_catalog import get_event
from modules.notifications.models import NotificationService


class NotificationServiceConfigItem(BaseModel):
    service_key: str = Field(min_length=1)
    external_link: str | None = None

    @field_validator("external_link")
    @classmethod
    def validate_external_link(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        parsed = urlparse(stripped)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("external_link must be a valid http(s) URL")
        return stripped


def normalize_service_config(raw: object) -> NotificationServiceConfigItem | None:
    if isinstance(raw, str):
        key = raw.strip()
        if not key:
            return None
        return NotificationServiceConfigItem(service_key=key, external_link=None)
    if isinstance(raw, dict):
        key = str(raw.get("service_key", "")).strip()
        if not key:
            return None
        link = raw.get("external_link")
        return NotificationServiceConfigItem(
            service_key=key,
            external_link=str(link).strip() if link else None,
        )
    return None


def normalize_notification_services(raw: list | None) -> list[NotificationServiceConfigItem]:
    if not raw:
        return []
    result: list[NotificationServiceConfigItem] = []
    seen: set[str] = set()
    for item in raw:
        cfg = normalize_service_config(item)
        if cfg is None or cfg.service_key in seen:
            continue
        seen.add(cfg.service_key)
        result.append(cfg)
    return result


def extract_service_keys(raw: list | None) -> list[str]:
    return [cfg.service_key for cfg in normalize_notification_services(raw)]


def get_external_link_for_service(raw: list | None, service_key: str) -> str | None:
    for cfg in normalize_notification_services(raw):
        if cfg.service_key == service_key:
            return cfg.external_link
    return None


def serialize_for_db(configs: list[NotificationServiceConfigItem]) -> list[dict]:
    return [cfg.model_dump(mode="json") for cfg in configs]


def configs_to_api(raw: list | None) -> list[dict]:
    return serialize_for_db(normalize_notification_services(raw))


async def validate_notification_service_configs(
    db: AsyncSession,
    *,
    notification_services: list | None,
    event_label: str | None = None,
) -> list[NotificationServiceConfigItem]:
    configs = normalize_notification_services(notification_services)
    if not configs:
        return []

    keys = [cfg.service_key for cfg in configs]
    result = await db.execute(
        select(NotificationService).where(NotificationService.service_key.in_(keys))
    )
    services_by_key = {svc.service_key: svc for svc in result.scalars().all()}

    prefix = f"{event_label}: " if event_label else ""
    for cfg in configs:
        svc = services_by_key.get(cfg.service_key)
        if svc is None:
            raise AppError(
                status_code=400,
                error_code="INVALID_INPUT",
                message=f"{prefix}Unknown notification service '{cfg.service_key}'",
            )
        if cfg.external_link is None and "external_link" in (cfg.service_key or ""):
            pass
    return configs


def _resolve_event_code_and_recipient(
    *,
    event_code: str | None,
    recipient_type: str | None,
) -> tuple[str, str]:
    code = (event_code or "").strip()
    if not code:
        raise AppError(
            status_code=400,
            error_code="INVALID_INPUT",
            message="event_code is required",
        )
    catalog = get_event(code)
    rt = (recipient_type or "").strip()
    if not rt:
        if catalog and catalog.recipient_types:
            rt = catalog.recipient_types[0]
        else:
            rt = "participant"
    return code, rt


async def prepare_notification_items_for_storage(
    db: AsyncSession,
    notifications: list[dict],
) -> list[dict]:
    prepared: list[dict] = []
    for item in notifications:
        if item.get("notification_event_id") is not None and not item.get("event_code"):
            raise AppError(
                status_code=400,
                error_code="INVALID_INPUT",
                message="notification_event_id is no longer supported; use event_code",
            )
        stored_event_code, recipient_type = _resolve_event_code_and_recipient(
            event_code=item.get("event_code"),
            recipient_type=item.get("recipient_type"),
        )
        event_label = f"Event {stored_event_code}"
        configs = await validate_notification_service_configs(
            db,
            notification_services=item.get("notification_services"),
            event_label=event_label,
        )
        if not configs:
            continue
        prepared.append({
            "notification_services": serialize_for_db(configs),
            "event_code": stored_event_code,
            "recipient_type": recipient_type,
        })
    return prepared
