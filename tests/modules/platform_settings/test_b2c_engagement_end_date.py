"""Unit tests for B2C engagement end date from inclusive duration window."""

from __future__ import annotations

from datetime import date

from modules.platform_settings.b2c_onboard_apply import b2c_engagement_end_date


def test_b2c_engagement_end_date_single_day():
    start = date(2026, 7, 15)
    assert b2c_engagement_end_date(start, 1) == start


def test_b2c_engagement_end_date_three_day_inclusive():
    start = date(2026, 7, 15)
    assert b2c_engagement_end_date(start, 3) == date(2026, 7, 17)


def test_b2c_engagement_end_date_seven_day_inclusive():
    start = date(2026, 7, 15)
    assert b2c_engagement_end_date(start, 7) == date(2026, 7, 21)