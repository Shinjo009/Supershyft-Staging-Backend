"""Shared KPI helpers: blood / Bio-AI report sent via notifications."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.dashboard.command_service import _stamp_period_clauses
from modules.engagements.models import Engagement, EngagementParticipant
from modules.notifications.models import Notification

EVENT_BLOOD_READY = "reports.blood_ready"
EVENT_BIOAI_READY = "reports.bioai_ready"
REPORT_SENT_CHANNELS = ("whatsapp", "email")


def notification_user_ids(raw_user: Any) -> set[int]:
    """Parse notifications.user.user_ids into a set of ints."""
    if not isinstance(raw_user, dict):
        return set()
    ids = raw_user.get("user_ids")
    if not isinstance(ids, list):
        return set()
    result: set[int] = set()
    for uid in ids:
        if uid is None:
            continue
        try:
            result.add(int(uid))
        except (TypeError, ValueError):
            continue
    return result


async def _enrolled_user_ids_by_engagement(
    db: AsyncSession,
    *,
    engagement_ids: Iterable[int],
) -> dict[int, set[int]]:
    ids = [int(eid) for eid in engagement_ids]
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(
                EngagementParticipant.engagement_id,
                EngagementParticipant.user_id,
            ).where(EngagementParticipant.engagement_id.in_(ids))
        )
    ).all()
    out: dict[int, set[int]] = {eid: set() for eid in ids}
    for engagement_id, user_id in rows:
        out.setdefault(int(engagement_id), set()).add(int(user_id))
    return out


async def report_sent_user_ids_for_engagement(
    db: AsyncSession,
    *,
    engagement_id: int,
    event_code: str,
) -> set[int]:
    """Distinct enrolled users with a matching sent WhatsApp/email notification."""
    eid = int(engagement_id)
    enrolled = (
        await _enrolled_user_ids_by_engagement(db, engagement_ids=[eid])
    ).get(eid, set())
    if not enrolled:
        return set()

    rows = (
        await db.execute(
            select(Notification.user).where(
                Notification.engagement_id == eid,
                Notification.event_code == event_code,
                Notification.channel.in_(REPORT_SENT_CHANNELS),
                Notification.status == "sent",
            )
        )
    ).all()

    matched: set[int] = set()
    for (user_payload,) in rows:
        matched.update(notification_user_ids(user_payload) & enrolled)
    return matched


async def count_report_sent_for_engagement(
    db: AsyncSession,
    *,
    engagement_id: int,
    event_code: str,
) -> int:
    return len(
        await report_sent_user_ids_for_engagement(
            db,
            engagement_id=engagement_id,
            event_code=event_code,
        )
    )


async def b2c_report_sent_user_ids(
    db: AsyncSession,
    *,
    event_code: str,
    dispatched_from: datetime | None,
    dispatched_to: datetime | None,
    all_time: bool,
) -> list[int]:
    """Distinct B2C users (org_id null) with report-sent notification in period."""
    query = (
        select(
            Notification.engagement_id,
            Notification.user,
            Notification.dispatched_at,
            Notification.notification_id,
        )
        .select_from(Notification)
        .join(Engagement, Engagement.engagement_id == Notification.engagement_id)
        .where(
            Engagement.organization_id.is_(None),
            Notification.event_code == event_code,
            Notification.channel.in_(REPORT_SENT_CHANNELS),
            Notification.status == "sent",
            Notification.engagement_id.is_not(None),
        )
    )
    for clause in _stamp_period_clauses(
        Notification.dispatched_at,
        stamp_from=dispatched_from,
        stamp_to=dispatched_to,
        all_time=all_time,
    ):
        query = query.where(clause)

    rows = (await db.execute(query)).all()
    if not rows:
        return []

    engagement_ids = {int(r.engagement_id) for r in rows if r.engagement_id is not None}
    enrolled_by_eng = await _enrolled_user_ids_by_engagement(
        db, engagement_ids=engagement_ids
    )

    # Prefer latest dispatched_at per user; notification_id as tie-breaker.
    best: dict[int, tuple[datetime | None, int]] = {}
    for engagement_id, user_payload, dispatched_at, notification_id in rows:
        eid = int(engagement_id)
        enrolled = enrolled_by_eng.get(eid) or set()
        nid = int(notification_id)
        for uid in notification_user_ids(user_payload) & enrolled:
            prev = best.get(uid)
            if prev is None:
                best[uid] = (dispatched_at, nid)
                continue
            prev_at, prev_nid = prev
            if dispatched_at is not None and (
                prev_at is None
                or dispatched_at > prev_at
                or (dispatched_at == prev_at and nid > prev_nid)
            ):
                best[uid] = (dispatched_at, nid)
            elif dispatched_at is None and prev_at is None and nid > prev_nid:
                best[uid] = (dispatched_at, nid)

    return sorted(best.keys(), reverse=True)


async def blood_report_sent_pairs(
    db: AsyncSession,
    *,
    user_engagement_pairs: Iterable[tuple[int, int]],
) -> set[tuple[int, int]]:
    """Return (user_id, engagement_id) pairs with blood report sent notification."""
    pairs = {(int(uid), int(eid)) for uid, eid in user_engagement_pairs}
    if not pairs:
        return set()

    engagement_ids = {eid for _, eid in pairs}
    user_ids = {uid for uid, _ in pairs}

    rows = (
        await db.execute(
            select(
                Notification.engagement_id,
                Notification.user,
            ).where(
                Notification.engagement_id.in_(list(engagement_ids)),
                Notification.event_code == EVENT_BLOOD_READY,
                Notification.channel.in_(REPORT_SENT_CHANNELS),
                Notification.status == "sent",
            )
        )
    ).all()

    matched: set[tuple[int, int]] = set()
    for engagement_id, user_payload in rows:
        eid = int(engagement_id)
        for uid in notification_user_ids(user_payload):
            if uid in user_ids and (uid, eid) in pairs:
                matched.add((uid, eid))
    return matched
