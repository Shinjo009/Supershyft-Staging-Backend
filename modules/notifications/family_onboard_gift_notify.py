"""Diwali family-onboard gift notifications (booker + receiver, WhatsApp + email)."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from modules.notifications.dedup import should_skip_notification
from modules.notifications.onboarding_notify import detail_or_hyphen
from modules.notifications.repository import NotificationsRepository
from modules.notifications.schemas import DispatchRequest
from modules.notifications.service import NotificationsService

if TYPE_CHECKING:
    from modules.users.models import User

logger = logging.getLogger(__name__)

GIFT_URL = "https://app.supershyft.com"

SENDER_WHATSAPP_KEY = "family-onboard-sender-whatsapp"
SENDER_EMAIL_KEY = "family-onboard-sender-email"
RECEIVER_WHATSAPP_KEY = "family-onboard-receiver-whatsapp"
RECEIVER_EMAIL_KEY = "family-onboard-receiver-email"

_ALL_KEYS: tuple[str, ...] = (
    SENDER_WHATSAPP_KEY,
    SENDER_EMAIL_KEY,
    RECEIVER_WHATSAPP_KEY,
    RECEIVER_EMAIL_KEY,
)


def _display_name(user: User) -> str:
    first = (getattr(user, "first_name", None) or "").strip()
    last = (getattr(user, "last_name", None) or "").strip()
    name = f"{first} {last}".strip()
    return name if name else "there"


def _format_relationship(relation: str | None) -> str:
    raw = (relation or "").strip().replace("_", " ")
    if not raw:
        return "-"
    return raw.title()


def _is_booker_plus_alias_email(recipient_email: str | None, booker_email: str | None) -> bool:
    """True when recipient email is a `{booker_local}+NNNN@domain` alias."""
    if not recipient_email or not booker_email or "@" not in recipient_email or "@" not in booker_email:
        return False
    r_local, r_domain = recipient_email.split("@", 1)
    b_local, b_domain = booker_email.split("@", 1)
    if r_domain.lower() != b_domain.lower():
        return False
    return bool(re.fullmatch(rf"{re.escape(b_local)}\+\d{{4}}", r_local, flags=re.IGNORECASE))


def _participant_details(
    *,
    booker: User,
    recipient: User,
    relationship: str | None,
) -> dict[str, str]:
    return {
        "booker_name": detail_or_hyphen(_display_name(booker)),
        "recipient_name": detail_or_hyphen(_display_name(recipient)),
        "relationship": detail_or_hyphen(_format_relationship(relationship)),
        "gift_url": GIFT_URL,
    }


def _should_skip_receiver_email(recipient: User, booker: User) -> bool:
    email = (getattr(recipient, "email", None) or "").strip()
    if not email:
        return True
    return _is_booker_plus_alias_email(email, getattr(booker, "email", None))


async def _dispatch_one(
    db: AsyncSession,
    *,
    notifications_service: NotificationsService,
    notifications_repository: NotificationsRepository,
    service_key: str,
    user_id: int,
    engagement_id: int,
    participant_details: dict[str, str],
) -> None:
    try:
        svc = await notifications_repository.get_service_by_key(db, service_key=service_key)
        if svc is None:
            logger.warning(
                "Family onboard gift skipped: service_key=%s not found (engagement_id=%s)",
                service_key,
                engagement_id,
            )
            return
        if not svc.is_active:
            logger.warning(
                "Family onboard gift skipped: service_key=%s inactive (engagement_id=%s)",
                service_key,
                engagement_id,
            )
            return

        skip_reason = await should_skip_notification(
            db,
            service_key=service_key,
            user_id=user_id,
            engagement_id=engagement_id,
            repository=notifications_repository,
        )
        if skip_reason:
            logger.info(
                "Family onboard gift skipped: service_key=%s user=%s engagement=%s reason=%s",
                service_key,
                user_id,
                engagement_id,
                skip_reason,
            )
            return

        await notifications_service.dispatch(
            db,
            payload=DispatchRequest(
                service_key=service_key,
                user_ids=[user_id],
                engagement_id=engagement_id,
                participant_details=participant_details,
            ),
            triggered_by_user_id=None,
        )
    except Exception as exc:
        logger.warning(
            "Family onboard gift failed: service_key=%s user=%s engagement=%s: %s",
            service_key,
            user_id,
            engagement_id,
            exc,
        )


async def notify_family_onboard_gift(
    db: AsyncSession,
    *,
    notifications_service: NotificationsService | None,
    booker: User,
    recipient: User,
    engagement_id: int,
    relationship: str | None,
) -> None:
    """Best-effort gift notifications after family-onboard payment confirm."""
    if notifications_service is None:
        return

    repo = notifications_service._repo
    details = _participant_details(booker=booker, recipient=recipient, relationship=relationship)
    booker_id = int(booker.user_id)
    recipient_id = int(recipient.user_id)
    eid = int(engagement_id)

    await _dispatch_one(
        db,
        notifications_service=notifications_service,
        notifications_repository=repo,
        service_key=SENDER_WHATSAPP_KEY,
        user_id=booker_id,
        engagement_id=eid,
        participant_details=details,
    )
    await _dispatch_one(
        db,
        notifications_service=notifications_service,
        notifications_repository=repo,
        service_key=SENDER_EMAIL_KEY,
        user_id=booker_id,
        engagement_id=eid,
        participant_details=details,
    )
    await _dispatch_one(
        db,
        notifications_service=notifications_service,
        notifications_repository=repo,
        service_key=RECEIVER_WHATSAPP_KEY,
        user_id=recipient_id,
        engagement_id=eid,
        participant_details=details,
    )
    if not _should_skip_receiver_email(recipient, booker):
        await _dispatch_one(
            db,
            notifications_service=notifications_service,
            notifications_repository=repo,
            service_key=RECEIVER_EMAIL_KEY,
            user_id=recipient_id,
            engagement_id=eid,
            participant_details=details,
        )


__all__ = [
    "GIFT_URL",
    "SENDER_WHATSAPP_KEY",
    "SENDER_EMAIL_KEY",
    "RECEIVER_WHATSAPP_KEY",
    "RECEIVER_EMAIL_KEY",
    "_ALL_KEYS",
    "_is_booker_plus_alias_email",
    "_should_skip_receiver_email",
    "notify_family_onboard_gift",
]
