"""Dispatch consultation guide notifications for configured engagement recipients.

Targets whoever is selected on the engagement's ``reminders.consultation_guide``
slots (e.g. expert assistants and/or staff assistants) for engagements with an
enabled consultation date tomorrow in ``slot_detail.consultation``. Re-runs skip
recipients that already succeeded or are still in flight; failed recipients are retried.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from modules.engagement_notifications.service_config import (
    merge_notification_service_configs,
    normalize_notification_services,
)
from modules.engagements.repository import EngagementsRepository
from modules.notifications.binding_resolver import BindingResolver, ResolvedBinding
from modules.notifications.dedup import should_skip_contact_notification
from modules.notifications.pretest_reminders import tomorrow_in_ist
from modules.notifications.recipient_resolver import RecipientResolver
from modules.notifications.service import NotificationsService

logger = logging.getLogger(__name__)

_IST = ZoneInfo("Asia/Kolkata")
_CONSULTATION_GUIDE_EVENT = "reminders.consultation_guide"


def _contact_identity(contact: dict) -> dict[str, Any]:
    partner_id = contact.get("partner_id")
    employee_id = contact.get("employee_id")
    return {
        "partner_id": partner_id if isinstance(partner_id, int) else None,
        "employee_id": employee_id if isinstance(employee_id, int) else None,
        "phone": str(contact.get("phone") or "").strip() or None,
        "email": str(contact.get("email") or "").strip().lower() or None,
        "name": str(contact.get("name") or "").strip() or None,
        "role": contact.get("role"),
        "kind": contact.get("kind"),
    }


def _exc_message(exc: BaseException) -> str:
    message = getattr(exc, "message", None)
    if isinstance(message, str) and message.strip():
        return message
    text = str(exc).strip()
    return text or type(exc).__name__


async def dispatch_consultation_guide_reminders(
    db: AsyncSession,
    *,
    notifications_service: NotificationsService,
    engagements_repository: EngagementsRepository,
    as_of: date | None = None,
    dry_run: bool = False,
    binding_resolver: BindingResolver | None = None,
    recipient_resolver: RecipientResolver | None = None,
) -> dict[str, int | str | bool | list[dict[str, Any]]]:
    """Notify configured consultation-guide recipients for consultation-tomorrow engagements."""
    consultation_date = tomorrow_in_ist(as_of=as_of)
    engagement_ids = await engagements_repository.list_engagements_for_consultation_guide_reminder(
        db,
        consultation_date=consultation_date,
    )

    bindings = binding_resolver or BindingResolver()
    recipients = recipient_resolver or RecipientResolver(
        engagements_repository=engagements_repository
    )

    matched = 0
    sent = 0
    skipped = 0
    failed = 0
    details: list[dict[str, Any]] = []

    for engagement_id in engagement_ids:
        resolved_bindings = await bindings.resolve(
            db,
            event_code=_CONSULTATION_GUIDE_EVENT,
            engagement_id=engagement_id,
            context={},
        )
        if not resolved_bindings:
            continue

        by_recipient: dict[str, list[ResolvedBinding]] = defaultdict(list)
        for binding in resolved_bindings:
            by_recipient[binding.recipient_type].append(binding)

        for recipient_type, group in by_recipient.items():
            service_configs = merge_notification_service_configs(
                *[
                    normalize_notification_services(binding.notification_services)
                    for binding in group
                ]
            )
            service_keys = [cfg.service_key for cfg in service_configs]
            recipient_config = next(
                (
                    binding.recipient_config
                    for binding in group
                    if isinstance(binding.recipient_config, dict)
                ),
                None,
            )
            target = await recipients.resolve(
                db,
                recipient_type=recipient_type,
                context={},
                engagement_id=engagement_id,
                recipient_config=recipient_config,
            )
            contacts = list(target.contacts or [])
            if not contacts:
                continue

            if dry_run:
                for contact in contacts:
                    matched += 1
                    identity = _contact_identity(contact)
                    details.append({
                        **identity,
                        "engagement_id": engagement_id,
                        "recipient_type": recipient_type,
                        "service_key": ",".join(service_keys) if service_keys else None,
                        "action": "dry_run",
                        "reason": (
                            "no notification keys configured"
                            if not service_keys
                            else "would dispatch"
                        ),
                    })
                continue

            if not service_configs:
                for contact in contacts:
                    matched += 1
                    skipped += 1
                    identity = _contact_identity(contact)
                    details.append({
                        **identity,
                        "engagement_id": engagement_id,
                        "recipient_type": recipient_type,
                        "action": "skipped",
                        "reason": "no notification keys configured",
                    })
                continue

            for contact in contacts:
                matched += 1
                identity = _contact_identity(contact)
                dispatched_any = False
                skipped_all = True
                failed_any = False

                skip_reason = await should_skip_contact_notification(
                    db,
                    event_code=_CONSULTATION_GUIDE_EVENT,
                    engagement_id=engagement_id,
                    partner_id=identity["partner_id"],
                    employee_id=identity["employee_id"],
                    phone=identity["phone"],
                    email=identity["email"],
                )
                if skip_reason:
                    skipped += 1
                    details.append({
                        **identity,
                        "engagement_id": engagement_id,
                        "recipient_type": recipient_type,
                        "service_key": ",".join(service_keys) if service_keys else None,
                        "action": "skipped",
                        "reason": f"notification '{_CONSULTATION_GUIDE_EVENT}' {skip_reason}",
                    })
                    continue

                for cfg in service_configs:
                    sk = cfg.service_key
                    try:
                        skipped_all = False
                        await notifications_service.dispatch_to_contacts(
                            db,
                            service_key=sk,
                            contacts=[contact],
                            engagement_id=engagement_id,
                            event_code=_CONSULTATION_GUIDE_EVENT,
                        )
                        dispatched_any = True
                        details.append({
                            **identity,
                            "engagement_id": engagement_id,
                            "recipient_type": recipient_type,
                            "service_key": sk,
                            "action": "sent",
                            "reason": f"dispatched '{sk}'",
                        })
                    except Exception as exc:
                        failed_any = True
                        reason = _exc_message(exc)
                        details.append({
                            **identity,
                            "engagement_id": engagement_id,
                            "recipient_type": recipient_type,
                            "service_key": sk,
                            "action": "failed",
                            "reason": reason,
                        })
                        logger.warning(
                            "Consultation guide reminder dispatch failed: "
                            "service_key=%s partner_id=%s employee_id=%s "
                            "engagement_id=%s recipient_type=%s: %s",
                            sk,
                            identity["partner_id"],
                            identity["employee_id"],
                            engagement_id,
                            recipient_type,
                            reason,
                        )

                if dispatched_any:
                    sent += 1
                elif failed_any:
                    failed += 1
                elif skipped_all:
                    skipped += 1

    return {
        "as_of": (as_of or datetime.now(_IST).date()).isoformat(),
        "consultation_date": consultation_date.isoformat(),
        "matched": matched,
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
        "dry_run": dry_run,
        "details": details,
    }