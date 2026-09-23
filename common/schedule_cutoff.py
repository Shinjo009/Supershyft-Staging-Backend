"""Lead-time gates for user reschedule / cancel of blood collection and consultations."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from core.exceptions import AppError

_IST = ZoneInfo("Asia/Kolkata")
DEFAULT_MIN_LEAD = timedelta(hours=12)

MSG_BLOOD_COLLECTION_RESCHEDULE = (
    "blood_collection rescheduling happens before 12 hrs of engagement_date of the "
    "participaints + slot_start_time of the Participaints"
)
MSG_CONSULTATION_RESCHEDULE = (
    "consultation rescheduling happens before 12 hrs of  consultation_date+consultation_slot "
    "of the participaints"
)
MSG_CONSULTATION_CANCEL = (
    "cancel consultation happen before 12 hrs consultation_date+consultation_slot of the participaints"
)


def _coerce_slot(appointment_slot: time | str | None) -> time | None:
    if appointment_slot is None:
        return None
    if isinstance(appointment_slot, time):
        return time(appointment_slot.hour, appointment_slot.minute)
    raw = str(appointment_slot).strip()
    if not raw:
        return None
    parts = raw.split(":")
    if len(parts) < 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return time(hour, minute)


def ensure_schedule_change_allowed(
    appointment_date: date | None,
    appointment_slot: time | str | None,
    *,
    message: str,
    now: datetime | None = None,
    min_lead: timedelta = DEFAULT_MIN_LEAD,
) -> None:
    """Reject when the current appointment date is past or within ``min_lead`` of start (IST)."""
    slot = _coerce_slot(appointment_slot)
    if appointment_date is None or slot is None:
        raise AppError(
            status_code=422,
            error_code="INVALID_STATE",
            message="Current appointment date and slot are required",
        )

    now_ist = now or datetime.now(_IST)
    if now_ist.tzinfo is None:
        now_ist = now_ist.replace(tzinfo=_IST)
    else:
        now_ist = now_ist.astimezone(_IST)

    if appointment_date < now_ist.date():
        raise AppError(
            status_code=422,
            error_code="SCHEDULE_CHANGE_CUTOFF",
            message=message,
        )

    appointment_at = datetime.combine(appointment_date, slot, tzinfo=_IST)
    if now_ist >= appointment_at - min_lead:
        raise AppError(
            status_code=422,
            error_code="SCHEDULE_CHANGE_CUTOFF",
            message=message,
        )
