"""Dispatch support-query notifications to default onboarding assistants (staff employees)."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.notifications.engine import get_notification_engine
from modules.notifications.participant_user_context import user_notification_context
from modules.platform_settings.repository import PlatformSettingsRepository
from modules.support.models import SupportTicket

logger = logging.getLogger(__name__)


def participant_details_from_support_ticket(
    user,
    *,
    ticket: SupportTicket,
) -> dict[str, object]:
    participant_user_id = str(ticket.user_id or getattr(user, "user_id", "") or "")
    return {
        "user": user_notification_context(user),
        "support": {
            "ticket_id": str(ticket.ticket_id),
            "query_text": str(ticket.query_text or ""),
        },
        "participant_user_id": participant_user_id,
    }


async def notify_default_onboarding_assistants_on_support_query(
    db: AsyncSession,
    *,
    notifications_service=None,
    notifications_repository=None,
    platform_settings_repository: PlatformSettingsRepository | None = None,
    ticket: SupportTicket,
    user,
) -> None:
    """Emit support.ticket_created using bindings from Notifications."""
    _ = notifications_service
    _ = notifications_repository
    _ = platform_settings_repository

    details = participant_details_from_support_ticket(user, ticket=ticket)
    try:
        await get_notification_engine().emit(
            db,
            event_code="support.ticket_created",
            context={
                "participant_details": details,
                "user_id": ticket.user_id,
            },
        )
    except Exception as exc:
        logger.warning(
            "Support notification failed for ticket_id=%s: %s",
            ticket.ticket_id,
            str(exc),
        )