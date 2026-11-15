"""Unit tests for command-center period + latest-engagement helpers."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from core.exceptions import AppError
from modules.dashboard.command_period import pick_latest_engagement, resolve_period_bounds
from modules.dashboard.command_service import (
    _bio_ai_status,
    _consult_status,
    _lab_status,
    _questionnaire_status_label,
)


def test_resolve_this_week_bounds():
    today = date(2026, 11, 15)  # Sunday
    start, end, preset = resolve_period_bounds(period="this_week", today=today)
    assert preset == "this_week"
    assert start is not None and end is not None
    assert start.date() == date(2026, 11, 9)  # Monday
    assert end.date() == date(2026, 11, 15)


def test_resolve_all_time_has_no_bounds():
    start, end, preset = resolve_period_bounds(period="all_time")
    assert preset == "all_time"
    assert start is None and end is None


def test_resolve_custom_requires_dates():
    with pytest.raises(AppError):
        resolve_period_bounds(period="custom")


def test_resolve_custom_bounds():
    start, end, preset = resolve_period_bounds(
        period="custom",
        from_date=date(2026, 1, 1),
        to_date=date(2026, 1, 31),
    )
    assert preset == "custom"
    assert start == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert end.date() == date(2026, 1, 31)


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


def test_status_helpers():
    assert _lab_status(has_engagement=False, diagnostic_report_url=None) == "empty"
    assert _lab_status(has_engagement=True, diagnostic_report_url=None) == "pending"
    assert _lab_status(has_engagement=True, diagnostic_report_url="https://x") == "loaded"
    assert _bio_ai_status(has_engagement=True, report_url="") == "pending"
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
