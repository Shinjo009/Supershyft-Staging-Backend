"""Tests for Orange Health slot normalization."""

from modules.diagnostics.orange_health.booking_helpers import slim_orange_health_slots


def test_slim_orange_health_slots_sorts_by_datetime():
    slots = {
        "2026-02-28T21:30:00": {
            "slot_datetime": "2026-02-28T21:30:00",
            "is_evening_slot": True,
        },
        "2026-02-28T06:00:00": {
            "slot_datetime": "2026-02-28T06:00:00",
            "is_morning_slot": True,
        },
    }
    out = slim_orange_health_slots(slots)
    assert len(out) == 2
    assert out[0]["stm_id"] == "2026-02-28T06:00:00"
    assert out[1]["stm_id"] == "2026-02-28T21:30:00"
