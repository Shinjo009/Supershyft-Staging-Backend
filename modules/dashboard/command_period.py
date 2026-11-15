"""Timeline presets for command-center dashboard filters."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from core.exceptions import AppError

PeriodPreset = Literal[
    "this_week",
    "this_month",
    "this_quarter",
    "six_months",
    "one_year",
    "all_time",
    "custom",
]

VALID_PERIODS: set[str] = {
    "this_week",
    "this_month",
    "this_quarter",
    "six_months",
    "one_year",
    "all_time",
    "custom",
}


def _start_of_week(d: date) -> date:
    return d - timedelta(days=d.weekday())  # Monday


def _end_of_week(d: date) -> date:
    return _start_of_week(d) + timedelta(days=6)


def _start_of_quarter(d: date) -> date:
    q = (d.month - 1) // 3
    return date(d.year, q * 3 + 1, 1)


def _end_of_quarter(d: date) -> date:
    start = _start_of_quarter(d)
    if start.month == 10:
        return date(d.year, 12, 31)
    next_q = date(d.year, start.month + 3, 1)
    return next_q - timedelta(days=1)


def resolve_period_bounds(
    *,
    period: str | None,
    from_date: date | None = None,
    to_date: date | None = None,
    today: date | None = None,
) -> tuple[datetime | None, datetime | None, str]:
    """Return inclusive UTC datetime bounds and normalized period id.

    ``all_time`` returns ``(None, None)`` (no date filter).
    """
    day = today or datetime.now(timezone.utc).date()
    preset = (period or "this_week").strip().lower()
    if preset not in VALID_PERIODS:
        raise AppError(
            status_code=400,
            error_code="INVALID_INPUT",
            message=f"Invalid period: {period}",
        )

    if preset == "all_time":
        return None, None, preset

    if preset == "custom":
        if from_date is None or to_date is None:
            raise AppError(
                status_code=400,
                error_code="INVALID_INPUT",
                message="Custom period requires from and to dates",
            )
        if to_date < from_date:
            raise AppError(
                status_code=400,
                error_code="INVALID_INPUT",
                message="to must be on or after from",
            )
        start_d, end_d = from_date, to_date
    elif preset == "this_week":
        start_d, end_d = _start_of_week(day), _end_of_week(day)
    elif preset == "this_month":
        start_d = date(day.year, day.month, 1)
        if day.month == 12:
            end_d = date(day.year, 12, 31)
        else:
            end_d = date(day.year, day.month + 1, 1) - timedelta(days=1)
    elif preset == "this_quarter":
        start_d, end_d = _start_of_quarter(day), _end_of_quarter(day)
    elif preset == "six_months":
        start_d = day - timedelta(days=182)
        end_d = day
    elif preset == "one_year":
        try:
            start_d = date(day.year - 1, day.month, day.day)
        except ValueError:
            start_d = date(day.year - 1, 2, 28)
        end_d = day
    else:
        start_d, end_d = _start_of_week(day), _end_of_week(day)

    start_dt = datetime.combine(start_d, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end_d, time.max.replace(microsecond=999999), tzinfo=timezone.utc)
    return start_dt, end_dt, preset


def pick_latest_engagement(
    engagements: list[tuple[int, date | None]],
    *,
    today: date,
) -> int | None:
    """Pick latest engagement id using upcoming-first rule.

    ``engagements`` is a list of ``(engagement_id, start_date)``.
    - If any upcoming (start_date > today): earliest upcoming
    - Else: most recent past (start_date <= today), then highest engagement_id
    - Engagements with null start_date are treated as past and ordered last among past
    """
    if not engagements:
        return None

    upcoming: list[tuple[date, int]] = []
    past: list[tuple[date, int]] = []
    for eng_id, start in engagements:
        if start is not None and start > today:
            upcoming.append((start, eng_id))
        else:
            # null start_date sorts as very old
            past.append((start or date.min, eng_id))

    if upcoming:
        upcoming.sort(key=lambda x: (x[0], x[1]))
        return upcoming[0][1]

    past.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return past[0][1] if past else None
