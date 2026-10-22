"""Notification event engine — resolve bindings and dispatch."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.exceptions import AppError
from modules.engagement_notifications.repository import EngagementNotificationsRepository
from modules.engagement_notifications.service_config import (
    get_external_link_for_service,
    normalize_notification_services,
)
from modules.notifications.context_builder import build_dispatch_request
from modules.notifications.dedup import should_skip_notification, should_skip_notification_on_date
from modules.notifications.events_catalog import get_catalog_event
from modules.notifications.models import NotificationEvent
from modules.notifications.recipient_resolver import (
    recipient_uses_user_dispatch,
    resolve_recipients,
)
from modules.notifications.repository import NotificationsRepository
from modules.notifications.schemas import SessionDetails
from modules.notifications.service import NotificationsService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Binding:
    recipient_type: str
    notification_services: list
    event_name: str


async def _load_bindings(
    db: AsyncSession,
    *,
    event_code: str,
    engagement_id: int | None,
) -> list[_Binding]:
    catalog = get_catalog_event(event_code)
    event_name = catalog.event_name if catalog else event_code

    if engagement_id is not None:
        en_repo = EngagementNotificationsRepository()
        rows = await en_repo.list_for_engagement_and_event_code(
            db, engagement_id=engagement_id, event_code=event_code
        )
        if not rows:
            return []
        return [
            _Binding(
                recipient_type=row.recipient_type,
                notification_services=row.notification_services or [],
                event_name=event_name,
            )
            for row in rows
        ]

    result = await db.execute(
        select(NotificationEvent).where(NotificationEvent.event_code == event_code)
    )
    rows = list(result.scalars().all())
    return [
        _Binding(
            recipient_type=row.recipient_type,
            notification_services=row.notification_services or [],
            event_name=row.event_name or event_name,
        )
        for row in rows
    ]


def _validate_event_code(event_code: str) -> None:
    if get_catalog_event(event_code) is not None:
        return
    message = f"Unknown notification event_code: {event_code}"
    if settings.APP_ENVIRONMENT == "test":
        raise ValueError(message)
    logger.warning(message)


async def emit_notification_event(
    db: AsyncSession,
    event_code: str,
    payload: dict[str, Any],
    *,
    engagement_id: int | None = None,
    triggered_by_user_id: int | None = None,
    notifications_service: NotificationsService | None = None,
    skip_dedup: bool = False,
    dedup_reference_date: date | None = None,
) -> list[int]:
    """
    Emit a catalog event: resolve bindings, recipients, and dispatch.

    When engagement_id is set, only engagement_notifications rows apply (per-event
    service list; recipient_type from event_recipient_defaults). Otherwise platform
    notification_events bindings are used.
    """
    _validate_event_code(event_code)
    if get_catalog_event(event_code) is None:
        return []

    bindings = await _load_bindings(db, event_code=event_code, engagement_id=engagement_id)
    if not bindings:
        logger.info(
            "No notification bindings for event_code=%s engagement_id=%s",
            event_code,
            engagement_id,
        )
        return []

    svc_layer = notifications_service or NotificationsService(NotificationsRepository())
    repo = svc_layer._repo  # noqa: SLF001
    notification_ids: list[int] = []

    explicit_recipient = payload.get("recipient_type")
    if isinstance(explicit_recipient, str) and explicit_recipient.strip():
        bindings = [b for b in bindings if b.recipient_type == explicit_recipient.strip()]

    for binding in bindings:
        configs = normalize_notification_services(binding.notification_services)
        if not configs:
            continue

        override_contacts = payload.get("contacts")
        if isinstance(override_contacts, list) and override_contacts:
            recipients = [c for c in override_contacts if isinstance(c, dict)]
        else:
            recipients = await resolve_recipients(
                db,
                recipient_type=binding.recipient_type,
                payload=payload,
                engagement_id=engagement_id,
            )
        if not recipients:
            logger.info(
                "No recipients for event=%s recipient_type=%s",
                event_code,
                binding.recipient_type,
            )
            continue

        user_ids = recipient_uses_user_dispatch(recipients)

        for cfg in configs:
            service_key = cfg.service_key
            external_link = get_external_link_for_service(
                binding.notification_services, service_key
            )

            if not skip_dedup and engagement_id is not None and user_ids:
                for uid in user_ids:
                    if dedup_reference_date is not None:
                        reason = await should_skip_notification_on_date(
                            db,
                            service_key=service_key,
                            user_id=uid,
                            engagement_id=engagement_id,
                            reference_date=dedup_reference_date,
                        )
                    else:
                        reason = await should_skip_notification(
                            db,
                            service_key=service_key,
                            user_id=uid,
                            engagement_id=engagement_id,
                        )
                    if reason:
                        logger.info(
                            "Skipping event=%s service=%s user=%s: %s",
                            event_code,
                            service_key,
                            uid,
                            reason,
                        )
                        user_ids = [u for u in user_ids if u != uid]

            try:
                if user_ids:
                    req = build_dispatch_request(
                        service_key=service_key,
                        user_ids=user_ids,
                        payload=payload,
                        engagement_id=engagement_id,
                        external_link=external_link,
                    )
                    result = await svc_layer.dispatch(
                        db,
                        payload=req,
                        triggered_by_user_id=triggered_by_user_id,
                        event_code=event_code,
                        recipient_type=binding.recipient_type,
                    )
                else:
                    session_details = payload.get("session_details")
                    parsed_session: SessionDetails | None = None
                    if isinstance(session_details, SessionDetails):
                        parsed_session = session_details
                    elif isinstance(session_details, dict):
                        parsed_session = SessionDetails.model_validate(session_details)

                    result = await svc_layer.dispatch_to_contacts(
                        db,
                        service_key=service_key,
                        contacts=recipients,
                        otp=payload.get("otp"),
                        engagement_id=engagement_id,
                        participant_details=payload.get("participant_details"),
                        session_details=parsed_session,
                        event_code=event_code,
                        recipient_type=binding.recipient_type,
                    )
                nid = int(result["notification_id"])
                notification_ids.append(nid)
            except AppError as exc:
                logger.warning(
                    "Event dispatch failed event=%s service=%s: %s",
                    event_code,
                    service_key,
                    exc.message,
                )
            except Exception as exc:
                logger.exception(
                    "Event dispatch error event=%s service=%s: %s",
                    event_code,
                    service_key,
                    exc,
                )

    return notification_ids
