"""Unit tests for hardcoded notification events catalog."""

from __future__ import annotations

from modules.notifications.events_catalog import (
    LEGACY_MIGRATION_EVENT_CODES,
    RECIPIENT_TYPES,
    get_catalog_event,
    get_events_catalog,
)


def test_legacy_migration_event_codes_present():
    catalog_codes = {e["event_code"] for e in get_events_catalog()}
    missing = LEGACY_MIGRATION_EVENT_CODES - catalog_codes
    assert not missing, f"Missing legacy codes: {missing}"


def test_catalog_recipient_types_are_valid():
    for entry in get_events_catalog():
        for rt in entry["allowed_recipient_types"]:
            assert rt in RECIPIENT_TYPES


def test_required_prompt1_codes_exist():
    catalog_codes = {e["event_code"] for e in get_events_catalog()}
    assert "onboarding" in catalog_codes
    assert "otp_whatsapp" in catalog_codes
    assert "consultation_rescheduled" in catalog_codes


def test_get_catalog_event_unknown():
    assert get_catalog_event("not_a_real_event") is None
