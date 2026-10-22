"""Dispatch consultation remainder notifications on the day of a scheduled consultation."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from modules.engagements.repository import ConsultationRemainderParticipant, EngagementsRepository
from modules.engagements.slot_availability import resolve_consultation_cabin_display_name
from modules.notifications.engine import emit_notification_event, SessionDetails
from modules.notifications.service import NotificationsService

logger = logging.getLogger(__name__)

_IST = ZoneInfo("Asia/Kolkata")


def today_in_ist(*, as_of: date | None = None) -> date:
    """Return as_of or today in IST."""
    if as_of is not None:
        return as_of
    return datetime.now(_IST).date()


def _session_details_from_participant(
    participant: ConsultationRemainderParticipant,
) -> SessionDetails:
    cabin = resolve_consultation_cabin_display_name(
        participant.slot_detail,
        consultation_date=participant.consultation_date,
        cabin_key=participant.consultation_cabin,
    )
    return SessionDetails(
        want=participant.want,
        date=participant.consultation_date,
        slot=participant.consultation_slot or "",
        expert_type=participant.expert_type,
        cabin=cabin,
    )


async def dispatch_consultation_remainder_notifications(
    db: AsyncSession,
    *,
    notifications_service: NotificationsService,
    engagements_repository: EngagementsRepository,
    as_of: date | None = None,
    dry_run: bool = False,
) -> dict[str, int | str | bool | list[dict[str, Any]]]:
    """Notify participants with a consultation scheduled for today (IST)."""
    consultation_date = today_in_ist(as_of=as_of)
    participants = await engagements_repository.list_participants_for_consultation_remainder(
        db,
        consultation_date=consultation_date,
    )

    matched = len(participants)
    sent = 0
    skipped = 0
    failed = 0
    details: list[dict[str, Any]] = []
    reference_date = consultation_date.isoformat()

    if dry_run:
        for participant in participants:
            details.append({
                "user_id": participant.user_id,
                "engagement_id": participant.engagement_id,
                "expert_type": participant.expert_type,
                "service_key": ",".join(participant.service_keys) if participant.service_keys else None,
                "action": "dry_run",
                "reason": "no notification keys configured" if not participant.service_keys else "would dispatch",
            })
        return {
            "as_of": reference_date,
            "consultation_date": reference_date,
            "matched": matched,
            "sent": 0,
            "skipped": matched,
            "failed": 0,
            "dry_run": True,
            "details": details,
        }

    for participant in participants:
        if not participant.service_keys:
            skipped += 1
            details.append({
                "user_id": participant.user_id,
                "engagement_id": participant.engagement_id,
                "expert_type": participant.expert_type,
                "action": "skipped",
                "reason": "no notification keys configured",
            })
            continue

        try:
            session_details = _session_details_from_participant(participant)
            ids = await emit_notification_event(
                db,
                "consultation_remainder",
                {
                    "user_id": participant.user_id,
                    "session_details": session_details.model_dump(mode="json"),
                },
                engagement_id=participant.engagement_id,
                notifications_service=notifications_service,
                dedup_reference_date=consultation_date,
            )
            dispatched_any = bool(ids)
            if dispatched_any:
                details.append({
                    "user_id": participant.user_id,
                    "engagement_id": participant.engagement_id,
                    "expert_type": participant.expert_type,
                    "action": "sent",
                    "reason": "dispatched consultation_remainder",
                })
            else:
                details.append({
                    "user_id": participant.user_id,
                    "engagement_id": participant.engagement_id,
                    "expert_type": participant.expert_type,
                    "action": "skipped",
                    "reason": "no bindings or deduped",
                })

            if dispatched_any:
                sent += 1
            else:
                skipped += 1
        except Exception as exc:
            failed += 1
            details.append({
                "user_id": participant.user_id,
                "engagement_id": participant.engagement_id,
                "expert_type": participant.expert_type,
                "service_key": ",".join(participant.service_keys),
                "action": "failed",
                "reason": str(exc),
            })
            logger.warning(
                "Consultation remainder dispatch failed: service_keys=%s user_id=%s engagement_id=%s expert_type=%s: %s",
                ",".join(participant.service_keys),
                participant.user_id,
                participant.engagement_id,
                participant.expert_type,
                str(exc),
            )

    return {
        "as_of": reference_date,
        "consultation_date": reference_date,
        "matched": matched,
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
        "dry_run": False,
        "details": details,
    }
