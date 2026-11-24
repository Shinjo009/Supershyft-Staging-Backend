"""Tests for Orange Health reschedule helpers."""

from __future__ import annotations

import pytest

from core.exceptions import AppError
from modules.diagnostics.orange_health.reschedule_helpers import (
    ORANGE_RESCHEDULE_PARTNER_KEYS,
    build_orange_reschedule_partner_body,
    sanitize_orange_reschedule_patch_body,
    _find_matched_slot,
)
from modules.diagnostics.orange_health.sync_log_payload import extract_partner_body_from_log


def test_build_orange_reschedule_partner_body_exact_keys():
    body = build_orange_reschedule_partner_body(
        requested_slot_time="2026-11-27T09:00:00",
        reschedule_reason="Patient not available",
        reschedule_explanation="Needs later slot",
    )
    assert set(body.keys()) == set(ORANGE_RESCHEDULE_PARTNER_KEYS)


def test_build_orange_reschedule_partner_body_requires_reason():
    with pytest.raises(AppError) as exc:
        build_orange_reschedule_partner_body(
            requested_slot_time="2026-11-27T09:00:00",
            reschedule_reason="",
            reschedule_explanation="x",
        )
    assert exc.value.error_code == "INVALID_RESCHEDULE_REASON"


def test_sanitize_strips_extra_keys():
    raw = {
        "requested_slot_time": "2026-11-27T09:00:00",
        "reschedule_reason": "r",
        "reschedule_explanation": "e",
        "audit": {"operation": "reschedule"},
    }
    clean = sanitize_orange_reschedule_patch_body(raw)
    assert "audit" not in clean
    assert clean["reschedule_reason"] == "r"


def test_find_matched_slot_ist_lock_matches_utc_partner_key():
    from modules.diagnostics.orange_health.reschedule_helpers import _find_matched_slot

    slots = {
        "2026-11-27T03:30:00": {
            "slot_datetime": "2026-11-27T03:30:00",
            "is_morning_slot": True,
        }
    }
    matched = _find_matched_slot(slots, "2026-11-27T09:00:00")
    assert matched is not None
    assert matched["slot_datetime"] == "2026-11-27T03:30:00"


def test_find_matched_slot_by_key():
    slots = {
        "2026-11-27T09:00:00": {
            "slot_datetime": "2026-11-27T09:00:00",
            "is_morning_slot": True,
        }
    }
    matched = _find_matched_slot(slots, "2026-11-27T09:00:00")
    assert matched is not None
    assert matched["slot_datetime"] == "2026-11-27T09:00:00"


def test_extract_partner_body_from_envelope():
    payload = {
        "http_method": "PATCH",
        "body": {
            "requested_slot_time": "t",
            "reschedule_reason": "r",
            "reschedule_explanation": "e",
        },
    }
    assert extract_partner_body_from_log(payload)["requested_slot_time"] == "t"


@pytest.mark.asyncio
async def test_revalidate_slot_not_found_raises(monkeypatch):
    from modules.engagements.models import EngagementParticipant

    participant = EngagementParticipant(
        engagement_participant_id=1,
        engagement_id=1,
        user_id=1,
        latitude=12.97,
        longitude=77.59,
    )

    async def fake_check(**kwargs):
        return {"slots": {"2026-11-27T10:00:00": {"slot_datetime": "2026-11-27T10:00:00"}}}

    monkeypatch.setattr(
        "modules.diagnostics.orange_health.reschedule_helpers.orange_health_client.check_serviceability",
        fake_check,
    )

    from datetime import date

    from modules.diagnostics.orange_health.reschedule_helpers import revalidate_orange_reschedule_slot

    with pytest.raises(AppError) as exc:
        await revalidate_orange_reschedule_slot(
            participant=participant,
            blood_collection_date=date(2026, 11, 27),
            locked_slot_id="2026-11-27T09:00:00",
            blood_collection_time_slot="09:00 AM",
        )
    assert exc.value.error_code == "SLOT_NOT_AVAILABLE"


def test_extract_partner_body_from_legacy_flat():
    payload = {
        "audit": {"operation": "reschedule"},
        "requested_slot_time": "2026-11-27T09:00:00",
        "reschedule_reason": "r",
        "reschedule_explanation": "e",
    }
    body = extract_partner_body_from_log(payload)
    assert "audit" not in body
    assert body["reschedule_reason"] == "r"