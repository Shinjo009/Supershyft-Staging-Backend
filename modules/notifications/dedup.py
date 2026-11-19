"""Notification deduplication helpers for cron jobs."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, cast, func, or_, select, type_coerce
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from modules.notifications.expire_stale import DEFAULT_PENDING_TIMEOUT_HOURS
from modules.notifications.models import Notification
from modules.notifications.repository import NotificationsRepository

_IST = ZoneInfo("Asia/Kolkata")


def _ist_day_bounds_utc(reference_date: date) -> tuple[datetime, datetime]:
    """Return UTC bounds for reference_date in Asia/Kolkata."""
    start_ist = datetime.combine(reference_date, time.min, tzinfo=_IST)
    end_ist = datetime.combine(reference_date, time.max, tzinfo=_IST)
    return start_ist.astimezone(timezone.utc), end_ist.astimezone(timezone.utc)


def _normalized_event_code(event_code: str | None) -> str | None:
    code = (event_code or "").strip()
    return code or None


def _user_identity_filter(
    user_id: int,
    *,
    dedup_metadata: dict | None = None,
):
    user_col = cast(Notification.user, JSONB)
    user_filter = user_col["user_ids"].contains(type_coerce([user_id], JSONB))
    if not dedup_metadata:
        return user_filter
    clauses = [user_filter]
    for key, value in dedup_metadata.items():
        clauses.append(user_col["_dedup"][key].astext == str(value))
    return and_(*clauses)


async def should_skip_notification(
    db: AsyncSession,
    *,
    event_code: str,
    user_id: int,
    engagement_id: int,
    repository: NotificationsRepository | None = None,
    pending_timeout_hours: int | None = None,
    service_key: str | None = None,
    dedup_event_code: str | None = None,
) -> str | None:
    """Return a skip reason if dispatch should be skipped, else None.

    Skips when a prior notification for this event_code + user + engagement
    has status ``sent``, or when a non-stale ``pending`` row is still in flight.
    When ``event_code`` is absent on all historical rows, falls back to
  ``service_key`` only if provided (legacy rows before backfill).
    """
    code = _normalized_event_code(dedup_event_code or event_code)
    if code is None:
        return None

    repo = repository or NotificationsRepository()
    hours = (
        pending_timeout_hours
        if pending_timeout_hours is not None
        else DEFAULT_PENDING_TIMEOUT_HOURS
    )
    in_flight_cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    if await repo.has_in_flight_pending_notification(
        db,
        event_code=code,
        user_id=user_id,
        engagement_id=engagement_id,
        dispatched_after=in_flight_cutoff,
        service_key=service_key,
    ):
        return "already in flight"

    user_filter = cast(Notification.user, JSONB)["user_ids"].contains(
        type_coerce([user_id], JSONB)
    )
    event_query = (
        select(Notification.status)
        .where(Notification.event_code == code)
        .where(Notification.engagement_id == engagement_id)
        .where(user_filter)
    )
    event_result = await db.execute(event_query)
    event_statuses = [row[0] for row in event_result.all()]
    if event_statuses and any(status == "sent" for status in event_statuses):
        return "already sent"

    if service_key:
        legacy_query = (
            select(Notification.status)
            .where(Notification.service_key == service_key)
            .where(Notification.engagement_id == engagement_id)
            .where(Notification.event_code.is_(None))
            .where(user_filter)
        )
        legacy_result = await db.execute(legacy_query)
        legacy_statuses = [row[0] for row in legacy_result.all()]
        if legacy_statuses and any(status == "sent" for status in legacy_statuses):
            return "already sent"

    return None


async def should_skip_notification_by_service_key(
    db: AsyncSession,
    *,
    service_key: str,
    user_id: int,
    engagement_id: int,
    repository: NotificationsRepository | None = None,
    pending_timeout_hours: int | None = None,
) -> str | None:
    """Legacy dedupe when ``event_code`` is unknown (failed row or historical data)."""
    sk = (service_key or "").strip()
    if not sk:
        return None

    repo = repository or NotificationsRepository()
    hours = (
        pending_timeout_hours
        if pending_timeout_hours is not None
        else DEFAULT_PENDING_TIMEOUT_HOURS
    )
    in_flight_cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    if await repo.has_in_flight_pending_notification(
        db,
        event_code="",
        user_id=user_id,
        engagement_id=engagement_id,
        dispatched_after=in_flight_cutoff,
        service_key=sk,
    ):
        return "already in flight"

    user_filter = cast(Notification.user, JSONB)["user_ids"].contains(
        type_coerce([user_id], JSONB)
    )
    query = (
        select(Notification.status)
        .where(Notification.service_key == sk)
        .where(Notification.engagement_id == engagement_id)
        .where(user_filter)
    )
    result = await db.execute(query)
    statuses = [row[0] for row in result.all()]
    if not statuses:
        return None
    if any(status == "sent" for status in statuses):
        return "already sent"
    return None


async def has_notification_been_sent(
    db: AsyncSession,
    *,
    event_code: str,
    user_id: int,
    engagement_id: int,
) -> bool:
    """Return True if a notification was already sent for this user+engagement+event."""
    return (
        await should_skip_notification(
            db,
            event_code=event_code,
            user_id=user_id,
            engagement_id=engagement_id,
        )
        is not None
    )


def _contact_match_filter(
    *,
    partner_id: int | None,
    employee_id: int | None,
    phone: str | None,
    email: str | None,
):
    """JSONB containment filter matching one contact identity inside user.contacts."""
    contacts_col = cast(Notification.user, JSONB)["contacts"]
    if isinstance(partner_id, int):
        return contacts_col.contains(type_coerce([{"partner_id": partner_id}], JSONB))
    if isinstance(employee_id, int):
        return contacts_col.contains(type_coerce([{"employee_id": employee_id}], JSONB))
    phone_value = (phone or "").strip()
    if phone_value:
        return contacts_col.contains(type_coerce([{"phone": phone_value}], JSONB))
    email_value = (email or "").strip().lower()
    if email_value:
        return contacts_col.contains(type_coerce([{"email": email_value}], JSONB))
    return None


async def should_skip_contact_notification(
    db: AsyncSession,
    *,
    event_code: str,
    engagement_id: int,
    partner_id: int | None = None,
    employee_id: int | None = None,
    phone: str | None = None,
    email: str | None = None,
    pending_timeout_hours: int | None = None,
    service_key: str | None = None,
) -> str | None:
    """Return a skip reason for contact-based dispatch (partners/employees), else None."""
    code = _normalized_event_code(event_code)
    if code is None:
        return None

    contact_filter = _contact_match_filter(
        partner_id=partner_id,
        employee_id=employee_id,
        phone=phone,
        email=email,
    )
    if contact_filter is None:
        return None

    hours = (
        pending_timeout_hours
        if pending_timeout_hours is not None
        else DEFAULT_PENDING_TIMEOUT_HOURS
    )
    in_flight_cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    in_flight_query = (
        select(Notification.notification_id)
        .where(Notification.event_code == code)
        .where(Notification.engagement_id == engagement_id)
        .where(Notification.status == "pending")
        .where(Notification.dispatched_at.isnot(None))
        .where(Notification.dispatched_at >= in_flight_cutoff)
        .where(contact_filter)
        .limit(1)
    )
    if (await db.execute(in_flight_query)).scalar_one_or_none() is not None:
        return "already in flight"

    query = (
        select(Notification.status)
        .where(Notification.event_code == code)
        .where(Notification.engagement_id == engagement_id)
        .where(contact_filter)
    )
    result = await db.execute(query)
    statuses = [row[0] for row in result.all()]

    if statuses and any(status == "sent" for status in statuses):
        return "already sent"

    if service_key:
        legacy_query = (
            select(Notification.status)
            .where(Notification.service_key == service_key)
            .where(Notification.engagement_id == engagement_id)
            .where(Notification.event_code.is_(None))
            .where(contact_filter)
        )
        legacy_result = await db.execute(legacy_query)
        legacy_statuses = [row[0] for row in legacy_result.all()]
        if legacy_statuses and any(status == "sent" for status in legacy_statuses):
            return "already sent"

    if not statuses:
        return None
    if any(status == "sent" for status in statuses):
        return "already sent"
    return None


async def should_skip_notification_on_date(
    db: AsyncSession,
    *,
    event_code: str,
    user_id: int,
    engagement_id: int,
    reference_date: date,
    repository: NotificationsRepository | None = None,
    pending_timeout_hours: int | None = None,
    service_key: str | None = None,
    dedup_metadata: dict | None = None,
    dedup_event_code: str | None = None,
) -> str | None:
    """Return a skip reason if dispatch should be skipped for reference_date (IST), else None."""
    code = _normalized_event_code(dedup_event_code or event_code)
    if code is None:
        return None

    _ = repository
    hours = (
        pending_timeout_hours
        if pending_timeout_hours is not None
        else DEFAULT_PENDING_TIMEOUT_HOURS
    )
    in_flight_cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    day_start_utc, day_end_utc = _ist_day_bounds_utc(reference_date)
    user_filter = _user_identity_filter(user_id, dedup_metadata=dedup_metadata)
    dispatch_ts = func.coalesce(Notification.completed_at, Notification.dispatched_at)

    stored_code = _normalized_event_code(event_code)
    event_match = (
        Notification.event_code == code
        if stored_code is None or stored_code == code
        else or_(Notification.event_code == code, Notification.event_code == stored_code)
    )

    in_flight_query = (
        select(Notification.notification_id)
        .where(event_match)
        .where(Notification.engagement_id == engagement_id)
        .where(Notification.status == "pending")
        .where(Notification.dispatched_at.isnot(None))
        .where(Notification.dispatched_at >= in_flight_cutoff)
        .where(dispatch_ts >= day_start_utc)
        .where(dispatch_ts <= day_end_utc)
        .where(user_filter)
        .limit(1)
    )
    in_flight = (await db.execute(in_flight_query)).scalar_one_or_none()
    if in_flight is not None:
        return "already in flight"

    sent_query = (
        select(Notification.notification_id)
        .where(event_match)
        .where(Notification.engagement_id == engagement_id)
        .where(Notification.status == "sent")
        .where(
            or_(
                Notification.dispatched_at.isnot(None),
                Notification.completed_at.isnot(None),
            )
        )
        .where(dispatch_ts >= day_start_utc)
        .where(dispatch_ts <= day_end_utc)
        .where(user_filter)
        .limit(1)
    )
    sent = (await db.execute(sent_query)).scalar_one_or_none()
    if sent is not None:
        return "already sent"

    if service_key:
        legacy_sent_query = (
            select(Notification.notification_id)
            .where(Notification.service_key == service_key)
            .where(Notification.engagement_id == engagement_id)
            .where(Notification.event_code.is_(None))
            .where(Notification.status == "sent")
            .where(
                or_(
                    Notification.dispatched_at.isnot(None),
                    Notification.completed_at.isnot(None),
                )
            )
            .where(dispatch_ts >= day_start_utc)
            .where(dispatch_ts <= day_end_utc)
            .where(user_filter)
            .limit(1)
        )
        legacy_sent = (await db.execute(legacy_sent_query)).scalar_one_or_none()
        if legacy_sent is not None:
            return "already sent"

    return None