"""Support query notifications via event engine."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.notifications.engine import emit_notification_event
from modules.notifications.service import NotificationsService
from modules.support.models import SupportTicket

logger = logging.getLogger(__name__)


def participant_details_from_support_ticket(
    user,
    *,
    ticket: SupportTicket,
) -> dict[str, str]:
    first_name = getattr(user, "first_name", None) or ""
    last_name = getattr(user, "last_name", None) or ""
    name = f"{first_name} {last_name}".strip()
    return {
        "name": name,
        "email": str(getattr(user, "email", None) or ""),
        "phone": str(getattr(user, "phone", None) or ""),
        "contact_input": str(ticket.contact_input or ""),
        "query_text": str(ticket.query_text or ""),
        "ticket_id": str(ticket.ticket_id),
        "participant_user_id": str(ticket.user_id or getattr(user, "user_id", "") or ""),
    }


async def notify_default_onboarding_assistants_on_support_query(
    db: AsyncSession,
    *,
    notifications_service: NotificationsService,
    notifications_repository=None,
    platform_settings_repository=None,
    ticket: SupportTicket,
    user,
) -> None:
    details = participant_details_from_support_ticket(user, ticket=ticket)
    try:
        await emit_notification_event(
            db,
            "support_query_raised",
            {
                "user_id": ticket.user_id,
                "participant_details": details,
            },
            notifications_service=notifications_service,
        )
    except Exception as exc:
        logger.warning(
            "Support notification failed for ticket_id=%s: %s",
            ticket.ticket_id,
            exc,
        )
