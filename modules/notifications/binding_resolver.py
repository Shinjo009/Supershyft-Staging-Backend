"""Resolve notification event bindings (engagement override → global)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.engagement_notifications.service_config import (
    NotificationServiceConfigItem,
    normalize_notification_services,
)
from modules.engagements.models import EngagementNotification
from modules.notifications.bindings_repository import NotificationEventBindingsRepository
from modules.notifications.events_catalog import LEGACY_EVENT_CODE_MAP, get_event
from modules.notifications.models import NotificationEventBinding


@dataclass(frozen=True)
class ResolvedBinding:
    recipient_type: str
    notification_services: list[NotificationServiceConfigItem]
    custom_contacts: dict[str, Any] | None
    filters: dict[str, Any] | None
    source: str  # engagement | global


def _legacy_lookup_codes(event_code: str) -> list[str]:
    catalog = get_event(event_code)
    codes: list[str] = []
    if catalog and catalog.legacy_event_code:
        codes.append(catalog.legacy_event_code)
    for legacy, mapped in LEGACY_EVENT_CODE_MAP.items():
        if mapped == event_code and legacy not in codes:
            codes.append(legacy)
    if event_code not in codes:
        codes.append(event_code)
    return codes


def filters_match(filters: dict[str, Any] | None, payload: dict[str, Any]) -> bool:
    if not filters:
        return True
    expected_code = filters.get("discount_code")
    if expected_code is None and isinstance(filters.get("discount"), dict):
        expected_code = filters["discount"].get("discount_code")
    if expected_code is not None:
        discount = payload.get("discount") if isinstance(payload.get("discount"), dict) else {}
        actual = payload.get("discount_code") or discount.get("discount_code")
        return str(actual or "").strip() == str(expected_code).strip()
    service_key = filters.get("service_key")
    if service_key is not None:
        return str(payload.get("service_key") or "").strip() == str(service_key).strip()
    return True


def _binding_from_engagement_row(
    row: EngagementNotification,
    *,
    recipient_type: str,
) -> ResolvedBinding | None:
    configs = normalize_notification_services(row.notification_services)
    if not configs:
        return None
    return ResolvedBinding(
        recipient_type=recipient_type,
        notification_services=configs,
        custom_contacts=None,
        filters=None,
        source="engagement",
    )


def _binding_from_global_row(row: NotificationEventBinding) -> ResolvedBinding | None:
    if not row.is_active:
        return None
    raw_services = row.notification_services
    if isinstance(raw_services, list):
        normalized = normalize_notification_services(raw_services)
    else:
        normalized = []
    if not normalized:
        return None
    custom = row.custom_contacts if isinstance(row.custom_contacts, dict) else None
    filters = row.filters if isinstance(row.filters, dict) else None
    return ResolvedBinding(
        recipient_type=str(row.recipient_type),
        notification_services=normalized,
        custom_contacts=custom,
        filters=filters,
        source="global",
    )


def _event_code_matches(stored_code: str, event_code: str, legacy_codes: list[str]) -> bool:
    if stored_code == event_code:
        return True
    return stored_code in legacy_codes


async def resolve_bindings_for_event(
    db: AsyncSession,
    *,
    event_code: str,
    engagement_id: int | None,
    payload: dict[str, Any],
    bindings_repo: NotificationEventBindingsRepository | None = None,
) -> list[ResolvedBinding]:
    """Return merged bindings; engagement wins per recipient_type."""
    repo = bindings_repo or NotificationEventBindingsRepository()
    by_recipient: dict[str, ResolvedBinding] = {}

    if engagement_id is not None:
        legacy_codes = _legacy_lookup_codes(event_code)
        query = select(EngagementNotification).where(
            EngagementNotification.engagement_id == engagement_id
        )
        result = await db.execute(query)
        for en_row in result.scalars().all():
            stored_code = (en_row.event_code or "").strip()
            if not _event_code_matches(stored_code, event_code, legacy_codes):
                mapped = LEGACY_EVENT_CODE_MAP.get(stored_code, stored_code)
                if not _event_code_matches(mapped, event_code, legacy_codes):
                    continue
            rt = (en_row.recipient_type or "").strip() or str(
                payload.get("recipient_type") or "participant"
            )
            binding = _binding_from_engagement_row(en_row, recipient_type=rt)
            if binding and filters_match(binding.filters, payload):
                by_recipient[rt] = binding

    for global_row in await repo.list_active_by_event_code(db, event_code=event_code):
        binding = _binding_from_global_row(global_row)
        if binding is None:
            continue
        if not filters_match(binding.filters, payload):
            continue
        if binding.recipient_type not in by_recipient:
            by_recipient[binding.recipient_type] = binding

    explicit_rt = str(payload.get("recipient_type") or "").strip()
    if explicit_rt:
        binding = by_recipient.get(explicit_rt)
        return [binding] if binding else []

    return list(by_recipient.values())
