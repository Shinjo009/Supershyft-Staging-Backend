"""Tests for hardcoded notification events catalog."""

from __future__ import annotations

from modules.notifications.events_catalog import (
    ALL_EVENTS,
    LEGACY_EVENT_CODE_MAP,
    get_event,
)


def test_no_duplicate_event_codes():
    codes = [e.event_code for e in ALL_EVENTS]
    assert len(codes) == len(set(codes))


def test_live_event_count_at_least_twenty():
    live = [e for e in ALL_EVENTS if e.is_live_today]
    assert len(live) >= 20


def test_legacy_event_code_map_resolves_to_catalog():
    for _old, new_code in LEGACY_EVENT_CODE_MAP.items():
        assert get_event(new_code) is not None, f"Missing catalog event for legacy map target {new_code!r}"


def test_get_event_and_list_by_group():
    otp = get_event("auth.otp.sent")
    assert otp is not None
    assert otp.is_live_today is True
    from modules.notifications.events_catalog import list_events_by_group

    auth_events = list_events_by_group("auth")
    assert any(e.event_code == "auth.otp.sent" for e in auth_events)
