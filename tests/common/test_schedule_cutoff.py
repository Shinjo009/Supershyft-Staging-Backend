"""Unit tests for schedule change cutoff (12h lead / past date)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from common.schedule_cutoff import (
    MSG_BLOOD_COLLECTION_RESCHEDULE,
    MSG_CONSULTATION_CANCEL,
    MSG_CONSULTATION_RESCHEDULE,
    ensure_schedule_change_allowed,
)
from core.exceptions import AppError

_IST = ZoneInfo("Asia/Kolkata")


def test_allows_when_more_than_12_hours_remain():
    # Tomorrow 14:00 with now today 21:00 → ~17h remaining
    now = datetime(2026, 9, 23, 21, 0, tzinfo=_IST)
    ensure_schedule_change_allowed(
        date(2026, 9, 24),
        time(14, 0),
        message=MSG_BLOOD_COLLECTION_RESCHEDULE,
        now=now,
    )


def test_blocks_when_only_10_hours_remain():
    # Tomorrow 07:00 with now today 21:00 → ~10h remaining
    now = datetime(2026, 9, 23, 21, 0, tzinfo=_IST)
    with pytest.raises(AppError) as exc:
        ensure_schedule_change_allowed(
            date(2026, 9, 24),
            time(7, 0),
            message=MSG_BLOOD_COLLECTION_RESCHEDULE,
            now=now,
        )
    assert exc.value.status_code == 422
    assert exc.value.error_code == "SCHEDULE_CHANGE_CUTOFF"
    assert exc.value.message == MSG_BLOOD_COLLECTION_RESCHEDULE


def test_blocks_when_appointment_date_is_yesterday():
    now = datetime(2026, 9, 23, 12, 0, tzinfo=_IST)
    with pytest.raises(AppError) as exc:
        ensure_schedule_change_allowed(
            date(2026, 9, 22),
            "10:00",
            message=MSG_CONSULTATION_RESCHEDULE,
            now=now,
        )
    assert exc.value.error_code == "SCHEDULE_CHANGE_CUTOFF"
    assert exc.value.message == MSG_CONSULTATION_RESCHEDULE


def test_blocks_today_slot_already_passed():
    now = datetime(2026, 9, 23, 11, 0, tzinfo=_IST)
    with pytest.raises(AppError) as exc:
        ensure_schedule_change_allowed(
            date(2026, 9, 23),
            "10:00",
            message=MSG_CONSULTATION_CANCEL,
            now=now,
        )
    assert exc.value.message == MSG_CONSULTATION_CANCEL


def test_blocks_exactly_at_12_hour_boundary():
    # Appointment tomorrow 09:00; now today 21:00 → exactly 12h → blocked (>= cutoff)
    now = datetime(2026, 9, 23, 21, 0, tzinfo=_IST)
    with pytest.raises(AppError) as exc:
        ensure_schedule_change_allowed(
            date(2026, 9, 24),
            "09:00",
            message=MSG_CONSULTATION_CANCEL,
            now=now,
        )
    assert exc.value.error_code == "SCHEDULE_CHANGE_CUTOFF"


def test_allows_just_over_12_hours():
    now = datetime(2026, 9, 23, 20, 59, tzinfo=_IST)
    ensure_schedule_change_allowed(
        date(2026, 9, 24),
        "09:00",
        message=MSG_CONSULTATION_RESCHEDULE,
        now=now,
    )


def test_missing_date_or_slot_invalid_state():
    now = datetime(2026, 9, 23, 12, 0, tzinfo=_IST)
    with pytest.raises(AppError) as exc:
        ensure_schedule_change_allowed(
            None,
            time(9, 0),
            message=MSG_BLOOD_COLLECTION_RESCHEDULE,
            now=now,
        )
    assert exc.value.error_code == "INVALID_STATE"

    with pytest.raises(AppError) as exc2:
        ensure_schedule_change_allowed(
            date(2026, 9, 25),
            None,
            message=MSG_BLOOD_COLLECTION_RESCHEDULE,
            now=now,
        )
    assert exc2.value.error_code == "INVALID_STATE"


def test_accepts_hhmm_string_slot():
    now = datetime(2026, 9, 23, 8, 0, tzinfo=_IST)
    ensure_schedule_change_allowed(
        date(2026, 9, 25),
        "10:30",
        message=MSG_CONSULTATION_RESCHEDULE,
        now=now,
        min_lead=timedelta(hours=12),
    )
