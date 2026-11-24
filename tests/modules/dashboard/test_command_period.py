"""Unit tests for command-center period + latest-engagement helpers."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from core.exceptions import AppError
from modules.dashboard.command_period import (
    IST,
    bound_calendar_date,
    pick_latest_engagement,
    resolve_period_bounds,
)
from modules.dashboard.command_service import (
    _bio_ai_status,
    _b2b_start_date_filter,
    _consult_status,
    _date_period_clauses,
    _is_consultation_type,
    _lab_status,
    _questionnaire_status_label,
)
from modules.engagements.models import Engagement


def test_resolve_this_week_bounds_are_ist_converted_to_utc():
    today = date(2026, 11, 15)  # Sunday
    start, end, preset = resolve_period_bounds(period="this_week", today=today)
    assert preset == "this_week"
    assert start is not None and end is not None
    assert start == datetime.combine(
        date(2026, 11, 9), time.min, tzinfo=IST
    ).astimezone(timezone.utc)
    assert end == datetime.combine(
        date(2026, 11, 15), time.max.replace(microsecond=999999), tzinfo=IST
    ).astimezone(timezone.utc)
    # IST Monday 00:00 → previous Sunday 18:30 UTC
    assert start == datetime(2026, 11, 8, 18, 30, tzinfo=timezone.utc)


def test_resolve_all_time_has_no_bounds():
    start, end, preset = resolve_period_bounds(period="all_time")
    assert preset == "all_time"
    assert start is None and end is None


def test_resolve_custom_requires_dates():
    with pytest.raises(AppError):
        resolve_period_bounds(period="custom")


def test_resolve_custom_bounds_are_ist_converted_to_utc():
    start, end, preset = resolve_period_bounds(
        period="custom",
        from_date=date(2026, 1, 1),
        to_date=date(2026, 1, 31),
    )
    assert preset == "custom"
    assert start == datetime.combine(
        date(2026, 1, 1), time.min, tzinfo=IST
    ).astimezone(timezone.utc)
    assert end == datetime.combine(
        date(2026, 1, 31), time.max.replace(microsecond=999999), tzinfo=IST
    ).astimezone(timezone.utc)
    assert start.astimezone(ZoneInfo("Asia/Kolkata")).date() == date(2026, 1, 1)
    assert end.astimezone(ZoneInfo("Asia/Kolkata")).date() == date(2026, 1, 31)


def test_pick_latest_prefers_earliest_upcoming():
    today = date(2026, 11, 15)
    chosen = pick_latest_engagement(
        [
            (1, date(2026, 11, 1)),  # past
            (2, date(2026, 12, 10)),  # upcoming later
            (3, date(2026, 11, 20)),  # upcoming earliest
        ],
        today=today,
    )
    assert chosen == 3


def test_pick_latest_falls_back_to_most_recent_past():
    today = date(2026, 11, 15)
    chosen = pick_latest_engagement(
        [
            (10, date(2026, 10, 1)),
            (11, date(2026, 11, 10)),
            (12, date(2026, 9, 1)),
        ],
        today=today,
    )
    assert chosen == 11


def test_pick_latest_empty():
    assert pick_latest_engagement([], today=date(2026, 11, 15)) is None


def test_is_consultation_type_exact_only():
    assert _is_consultation_type("consultation", "Consultation") is True
    assert _is_consultation_type("consultation", None) is True
    assert _is_consultation_type(None, "Consultation") is True
    assert _is_consultation_type("blood_test_with_consultation", "Blood Test with Consultation") is False
    assert _is_consultation_type("bio_ai_with_consultation", "BioAI with Consultation") is False
    assert _is_consultation_type("blood_test", "Blood Test") is False
    assert _is_consultation_type("bio_ai", "BioAI") is False


def test_bound_calendar_date_recovers_ist_day_from_utc_week_start():
    start, end, _ = resolve_period_bounds(period="this_week", today=date(2026, 11, 15))
    assert start is not None and end is not None
    # UTC Sunday 18:30 must map back to IST Monday, not UTC Sunday.
    assert start == datetime(2026, 11, 8, 18, 30, tzinfo=timezone.utc)
    assert bound_calendar_date(start) == date(2026, 11, 9)
    assert bound_calendar_date(end) == date(2026, 11, 15)


def test_date_period_clauses_use_ist_calendar_days():
    start, end, _ = resolve_period_bounds(period="this_week", today=date(2026, 11, 15))
    clauses = _date_period_clauses(
        Engagement.start_date,
        stamp_from=start,
        stamp_to=end,
        all_time=False,
    )
    assert len(clauses) == 3
    compiled = [str(c) for c in clauses]
    assert any("IS NOT NULL" in c for c in compiled)
    # Bound values must be IST Mondays/Sundays, not the UTC-shifted dates.
    assert any(getattr(c.right, "value", None) == date(2026, 11, 9) for c in clauses)
    assert any(getattr(c.right, "value", None) == date(2026, 11, 15) for c in clauses)


def test_b2b_start_date_filter_uses_ist_calendar_days():
    start, end, _ = resolve_period_bounds(period="this_week", today=date(2026, 11, 15))
    clauses = _b2b_start_date_filter(
        start_from=start, start_to=end, all_time=False
    )
    assert clauses is not None
    assert any(getattr(c.right, "value", None) == date(2026, 11, 9) for c in clauses)
    assert any(getattr(c.right, "value", None) == date(2026, 11, 15) for c in clauses)
    assert _b2b_start_date_filter(
        start_from=start, start_to=end, all_time=True
    ) is None


def test_status_helpers():
    assert _lab_status(has_engagement=False, diagnostic_report_url=None) == "empty"
    assert _lab_status(has_engagement=True, diagnostic_report_url=None) == "pending"
    assert _lab_status(has_engagement=True, diagnostic_report_url="https://x") == "loaded"
    assert (
        _lab_status(
            has_engagement=True,
            diagnostic_report_url="https://x",
            report_sent=True,
        )
        == "sent"
    )
    assert (
        _lab_status(
            has_engagement=True,
            diagnostic_report_url=None,
            report_sent=True,
        )
        == "sent"
    )
    assert _bio_ai_status(has_engagement=True, report_url="") == "pending"
    assert (
        _bio_ai_status(
            has_engagement=True,
            report_url=None,
            report_sent=True,
        )
        == "sent"
    )
    assert _consult_status(has_engagement=True, want=True, done=True) == "Attended"
    assert _consult_status(has_engagement=True, want=True, done=False) == "Booked"
    assert _consult_status(has_engagement=True, want=False, done=False) == "Not Booked"
    assert (
        _questionnaire_status_label(
            has_engagement=True,
            instance_status="completed",
            supershyft_category_ids=[1],
            progress_by_category={},
            all_required_answered=None,
        )
        == "completed"
    )
    assert (
        _questionnaire_status_label(
            has_engagement=True,
            instance_status="active",
            supershyft_category_ids=[1, 2],
            progress_by_category={1: "complete", 2: "complete"},
            all_required_answered=None,
        )
        == "completed"
    )
