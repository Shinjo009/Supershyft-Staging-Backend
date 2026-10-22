"""Dispatch onboarding notifications via the event engine."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.notifications.engine import emit_notification_event
from modules.notifications.service import NotificationsService

logger = logging.getLogger(__name__)

_MISSING_DETAIL = "-"


def detail_or_hyphen(value: object | None) -> str:
    if value is None:
        return _MISSING_DETAIL
    text = str(value).strip()
    return text if text else _MISSING_DETAIL


def participant_details_from_user(
    user,
    *,
    source: str,
    participant_user_id: int,
    collection_date: str | None = None,
    collection_time: str | None = None,
    cabin_name: str | None = None,
) -> dict[str, str]:
    first_name = getattr(user, "first_name", None) or ""
    last_name = getattr(user, "last_name", None) or ""
    name = f"{first_name} {last_name}".strip()
    details: dict[str, str] = {
        "name": detail_or_hyphen(name),
        "email": detail_or_hyphen(getattr(user, "email", None)),
        "phone": detail_or_hyphen(getattr(user, "phone", None)),
        "engagement": detail_or_hyphen(source),
        "participant_user_id": str(participant_user_id),
        "age": detail_or_hyphen(getattr(user, "age", None)),
        "gender": detail_or_hyphen(getattr(user, "gender", None)),
        "address": detail_or_hyphen(getattr(user, "address", None)),
        "pincode": detail_or_hyphen(
            getattr(user, "pin_code", None) or getattr(user, "pincode", None)
        ),
        "collection_date": detail_or_hyphen(collection_date),
        "collection_time": detail_or_hyphen(collection_time),
        "cabin_name": detail_or_hyphen(cabin_name),
    }
    return details


def _with_participant_user_id(
    participant_details: dict[str, str] | None,
    participant_user_id: int,
) -> dict[str, str] | None:
    if participant_details is None:
        return None
    return {**participant_details, "participant_user_id": str(participant_user_id)}


async def notify_onboarding_assistants_on_enrollment(
    db: AsyncSession,
    *,
    notifications_service: NotificationsService,
    notifications_repository=None,
    engagements_repository=None,
    engagement,
    participant_user_id: int,
    participant_details: dict[str, str] | None,
) -> None:
    """Emit onboarding event for assigned onboarding assistants."""
    details = _with_participant_user_id(participant_details, participant_user_id)
    try:
        await emit_notification_event(
            db,
            "onboarding",
            {
                "user_id": participant_user_id,
                "participant_details": details,
            },
            engagement_id=int(engagement.engagement_id),
            notifications_service=notifications_service,
        )
    except Exception as exc:
        logger.warning(
            "Onboarding notification failed for engagement_id=%s: %s",
            engagement.engagement_id,
            exc,
        )
