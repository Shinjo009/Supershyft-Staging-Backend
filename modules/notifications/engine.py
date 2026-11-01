"""Event-driven notification engine."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.engagement_notifications.service_config import (
    NotificationServiceConfigItem,
    get_external_link_for_service,
)
from modules.notifications.binding_resolver import ResolvedBinding, resolve_bindings_for_event
from modules.notifications.context_builder import build_event_context
from modules.notifications.dedup import should_skip_notification
from modules.notifications.recipient_resolver import ResolvedRecipients, resolve_recipients
from modules.notifications.repository import NotificationsRepository
from modules.notifications.schemas import DispatchRequest, SessionDetails
from modules.notifications.service import NotificationsService

logger = logging.getLogger(__name__)


def _session_details_from_payload(payload: dict[str, Any]) -> SessionDetails | None:
    raw = payload.get("session_details")
    if raw is None:
        return None
    if isinstance(raw, SessionDetails):
        return raw
    if isinstance(raw, dict):
        try:
            return SessionDetails.model_validate(raw)
        except Exception:
            return None
    return None


def _filter_service_configs(
    configs: list[NotificationServiceConfigItem],
    payload: dict[str, Any],
) -> list[NotificationServiceConfigItem]:
    sk = str(payload.get("service_key") or "").strip()
    if sk:
        return [c for c in configs if c.service_key == sk]
    keys = payload.get("service_keys")
    if isinstance(keys, list) and keys:
        allowed = {str(k).strip() for k in keys if str(k).strip()}
        if allowed:
            filtered = [c for c in configs if c.service_key in allowed]
            if filtered:
                return filtered
    channel = str(payload.get("channel") or "").strip().lower()
    if channel in ("whatsapp", "email"):
        filtered: list[NotificationServiceConfigItem] = []
        for cfg in configs:
            if channel == "whatsapp" and "whatsapp" in cfg.service_key:
                filtered.append(cfg)
            elif channel == "email" and "email" in cfg.service_key:
                filtered.append(cfg)
            elif channel not in ("whatsapp", "email"):
                filtered.append(cfg)
        return filtered or configs
    return configs


async def emit_event(
    db: AsyncSession,
    *,
    event_code: str,
    payload: dict[str, Any],
    engagement_id: int | None = None,
    triggered_by_user_id: int | None = None,
    notifications_service: NotificationsService | None = None,
    notifications_repository: NotificationsRepository | None = None,
    honor_dedup: bool = True,
) -> list[int]:
    """Create notifications for configured bindings. Returns notification_ids."""
    svc = notifications_service or NotificationsService(repository=NotificationsRepository())
    repo = notifications_repository or NotificationsRepository()

    bindings = await resolve_bindings_for_event(
        db,
        event_code=event_code,
        engagement_id=engagement_id,
        payload=payload,
    )
    if not bindings:
        return []

    notification_ids: list[int] = []
    participant_details = payload.get("participant_details")
    if participant_details is not None and not isinstance(participant_details, dict):
        participant_details = None
    otp = str(payload.get("otp") or "").strip() or None
    session_details = _session_details_from_payload(payload)
    assessment_instance_id = payload.get("assessment_instance_id")
    if assessment_instance_id is not None:
        assessment_instance_id = int(assessment_instance_id)

    for binding in bindings:
        configs = _filter_service_configs(binding.notification_services, payload)
        if not configs:
            continue

        recipients = await resolve_recipients(
            db,
            recipient_type=binding.recipient_type,
            payload=payload,
            binding=binding,
            engagement_id=engagement_id,
        )

        dispatch_units: list[tuple[list[int], list[dict]]] = []
        if recipients.members_for_individual_dispatch:
            for member in recipients.members_for_individual_dispatch:
                uid = member.get("user_id")
                if isinstance(uid, int):
                    dispatch_units.append(([uid], []))
                else:
                    dispatch_units.append(([], [member]))
        elif recipients.user_ids:
            dispatch_units.append((recipients.user_ids, []))
        elif recipients.contacts:
            dispatch_units.append(([], recipients.contacts))
        else:
            continue

        for service_cfg in configs:
            service_key = service_cfg.service_key
            ns = await repo.get_service_by_key(db, service_key=service_key)
            if ns is None or not ns.is_active:
                continue

            external_link = get_external_link_for_service(
                [c.model_dump(mode="json") for c in binding.notification_services],
                service_key,
            ) or str(payload.get("external_link") or "").strip() or None

            for user_ids, contacts in dispatch_units:
                if user_ids:
                    for user_id in user_ids:
                        if honor_dedup and engagement_id is not None:
                            skip_reason = await should_skip_notification(
                                db,
                                service_key=service_key,
                                user_id=user_id,
                                engagement_id=engagement_id,
                                repository=repo,
                            )
                            if skip_reason:
                                continue
                        req = DispatchRequest(
                            service_key=service_key,
                            user_ids=[user_id],
                            engagement_id=engagement_id,
                            otp=otp,
                            participant_details=participant_details,
                            session_details=session_details,
                            external_link=external_link,
                            assessment_instance_id=assessment_instance_id,
                        )
                        try:
                            result = await svc.dispatch(
                                db,
                                payload=req,
                                triggered_by_user_id=triggered_by_user_id,
                                event_code=event_code,
                                recipient_type=binding.recipient_type,
                            )
                            notification_ids.append(int(result["notification_id"]))
                        except Exception as exc:
                            logger.warning(
                                "emit_event dispatch failed event=%s service=%s user=%s: %s",
                                event_code,
                                service_key,
                                user_id,
                                exc,
                            )
                elif contacts:
                    try:
                        result = await svc.dispatch_to_contacts(
                            db,
                            service_key=service_key,
                            contacts=contacts,
                            otp=otp,
                            engagement_id=engagement_id,
                            participant_details=participant_details,
                            session_details=session_details,
                            event_code=event_code,
                            recipient_type=binding.recipient_type,
                        )
                        notification_ids.append(int(result["notification_id"]))
                    except Exception as exc:
                        logger.warning(
                            "emit_event dispatch_to_contacts failed event=%s service=%s: %s",
                            event_code,
                            service_key,
                            exc,
                        )

    return notification_ids


async def emit_event_or_legacy(
    db: AsyncSession,
    *,
    event_code: str,
    payload: dict[str, Any],
    engagement_id: int | None = None,
    triggered_by_user_id: int | None = None,
    legacy_fn=None,
    notifications_service: NotificationsService | None = None,
    **_: Any,
) -> list[int]:
    """Legacy wrapper; n8n fallback and legacy_fn are ignored after cutover."""
    _ = legacy_fn
    return await emit_event(
        db,
        event_code=event_code,
        payload=payload,
        engagement_id=engagement_id,
        triggered_by_user_id=triggered_by_user_id,
        notifications_service=notifications_service,
    )
