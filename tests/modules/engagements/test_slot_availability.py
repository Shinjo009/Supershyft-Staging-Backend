"""Unit tests for cabin slot generation and public slot_detail reshape."""

from __future__ import annotations

from datetime import date, time

import pytest

from core.exceptions import AppError
from modules.engagements.slot_availability import (
    SLOT_UNAVAILABLE_CODE,
    SLOT_UNAVAILABLE_MESSAGE,
    build_cabin_slot_rows,
    build_public_slot_detail,
    capacity_for_slot,
    format_hhmm,
    generate_slot_starts,
    occupancy_key,
    require_available_blood_collection_slot,
    require_available_consultation_slot,
    resolve_blood_collection_cabin_display_name,
)


def test_generate_slot_starts_skips_lunch_break():
    slots = generate_slot_starts(
        "09:00",
        "17:00",
        30,
        [{"start_time": "13:00", "end_time": "14:00"}],
    )
    assert [format_hhmm(slot) for slot in slots] == [
        "09:00",
        "09:30",
        "10:00",
        "10:30",
        "11:00",
        "11:30",
        "12:00",
        "12:30",
        "14:00",
        "14:30",
        "15:00",
        "15:30",
        "16:00",
        "16:30",
    ]


def test_generate_slot_starts_without_breaks():
    slots = generate_slot_starts("09:00", "10:00", 30, [])
    assert [format_hhmm(slot) for slot in slots] == ["09:00", "09:30"]


def test_require_available_blood_collection_slot_rejects_break_and_unknown_cabin():
    slot_detail = {
        "blood_collection": {
            "2026-08-20": [
                {
                    "cabin_name": "Blood Test Cabin 1",
                    "cabin_key": "blood_test_cabin_1",
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "slot_duration": 30,
                    "capacity_per_slot": 6,
                    "breaks": [{"start_time": "13:00", "end_time": "14:00"}],
                    "is_active": True,
                }
            ]
        }
    }
    cabin = require_available_blood_collection_slot(
        slot_detail,
        collection_date=date(2026, 8, 20),
        cabin_key="blood_test_cabin_1",
        slot_time=time(9, 0),
    )
    assert cabin["cabin_key"] == "blood_test_cabin_1"

    with pytest.raises(AppError) as lunch:
        require_available_blood_collection_slot(
            slot_detail,
            collection_date=date(2026, 8, 20),
            cabin_key="blood_test_cabin_1",
            slot_time=time(13, 0),
        )
    assert lunch.value.error_code == SLOT_UNAVAILABLE_CODE
    assert lunch.value.message == SLOT_UNAVAILABLE_MESSAGE

    with pytest.raises(AppError) as missing:
        require_available_blood_collection_slot(
            slot_detail,
            collection_date=date(2026, 8, 20),
            cabin_key="no-such-cabin",
            slot_time=time(9, 0),
        )
    assert missing.value.error_code == SLOT_UNAVAILABLE_CODE


def test_build_public_slot_detail_applies_occupancy_and_skips_inactive():
    slot_detail = {
        "blood_collection": {
            "2026-08-20": [
                {
                    "cabin_name": "Blood Test Cabin 1",
                    "cabin_key": "blood_test_cabin_1",
                    "start_time": "09:00",
                    "end_time": "10:00",
                    "slot_duration": 30,
                    "capacity_per_slot": 6,
                    "breaks": [],
                    "is_active": True,
                },
                {
                    "cabin_name": "Inactive Cabin",
                    "cabin_key": "inactive_cabin",
                    "start_time": "09:00",
                    "end_time": "10:00",
                    "slot_duration": 30,
                    "capacity_per_slot": 6,
                    "breaks": [],
                    "is_active": False,
                },
            ]
        },
        "consultation": {
            "2026-08-20": [
                {
                    "cabin_name": "Consultation Cabin 1",
                    "cabin_key": "consultation_cabin_1",
                    "start_time": "09:00",
                    "end_time": "10:00",
                    "expert_type": "doctor",
                    "slot_duration": 30,
                    "capacity_per_slot": 1,
                    "breaks": [],
                    "is_active": True,
                }
            ]
        },
    }
    occupancy = {occupancy_key("blood_test_cabin_1", date(2026, 8, 20), time(9, 0)): 5}
    consultation_occupancy = {occupancy_key("consultation_cabin_1", date(2026, 8, 20), time(9, 0)): 1}
    public = build_public_slot_detail(slot_detail, occupancy, consultation_occupancy)
    blood_day = public["blood_collection"]["2026-08-20"]
    assert blood_day["is_enable"] is True
    blood_cabins = blood_day["cabins"]
    assert [cabin["cabin_key"] for cabin in blood_cabins] == ["blood_test_cabin_1"]
    assert blood_cabins[0]["available_slots"] == [
        {"slot": "09:00", "spot_left": 1},
        {"slot": "09:30", "spot_left": 6},
    ]
    consult_day = public["consultation"]["2026-08-20"]
    assert consult_day["is_enable"] is True
    consult_cabin = consult_day["cabins"][0]
    assert consult_cabin["expert_type"] == "doctor"
    consult_slots = consult_cabin["available_slots"]
    assert consult_slots == [
        {"slot": "09:00", "spot_left": 0},
        {"slot": "09:30", "spot_left": 1},
    ]


def test_require_available_consultation_slot_rejects_break_cabin_and_expert_type():
    slot_detail = {
        "consultation": {
            "2026-08-20": [
                {
                    "cabin_name": "Consultation Cabin 1",
                    "cabin_key": "consultation_cabin_1",
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "expert_type": "doctor",
                    "slot_duration": 30,
                    "capacity_per_slot": 1,
                    "breaks": [{"start_time": "13:00", "end_time": "14:00"}],
                    "is_active": True,
                }
            ]
        }
    }
    cabin = require_available_consultation_slot(
        slot_detail,
        expert_type="doctor",
        consultation_date=date(2026, 8, 20),
        cabin_key="consultation_cabin_1",
        slot_time=time(9, 0),
    )
    assert cabin["cabin_key"] == "consultation_cabin_1"

    cases = [
        {"consultation_date": date(2026, 8, 21), "cabin_key": "consultation_cabin_1", "slot_time": time(9, 0), "expert_type": "doctor"},
        {"consultation_date": date(2026, 8, 20), "cabin_key": "missing", "slot_time": time(9, 0), "expert_type": "doctor"},
        {"consultation_date": date(2026, 8, 20), "cabin_key": "consultation_cabin_1", "slot_time": time(13, 0), "expert_type": "doctor"},
        {"consultation_date": date(2026, 8, 20), "cabin_key": "consultation_cabin_1", "slot_time": time(9, 0), "expert_type": "nutritionist"},
    ]
    for kwargs in cases:
        with pytest.raises(AppError) as err:
            require_available_consultation_slot(slot_detail, **kwargs)
        assert err.value.error_code == SLOT_UNAVAILABLE_CODE
        assert err.value.message == SLOT_UNAVAILABLE_MESSAGE


def test_build_public_slot_detail_returns_none_when_unconfigured():
    assert build_public_slot_detail(None) is None
    assert build_public_slot_detail({}) is None


def test_build_public_slot_detail_includes_disabled_dates_with_empty_cabins():
    slot_detail = {
        "blood_collection": {
            "2026-08-20": {
                "is_enable": False,
                "cabins": [
                    {
                        "cabin_name": "Blood Test Cabin 1",
                        "cabin_key": "blood_test_cabin_1",
                        "start_time": "09:00",
                        "end_time": "10:00",
                        "slot_duration": 30,
                        "capacity_per_slot": 6,
                        "breaks": [],
                        "is_active": True,
                    }
                ],
            },
            "2026-08-21": {
                "is_enable": True,
                "cabins": [
                    {
                        "cabin_name": "Blood Test Cabin 2",
                        "cabin_key": "blood_test_cabin_2",
                        "start_time": "09:00",
                        "end_time": "10:00",
                        "slot_duration": 30,
                        "capacity_per_slot": 6,
                        "breaks": [],
                        "is_active": True,
                    }
                ],
            },
        }
    }
    public = build_public_slot_detail(slot_detail)
    assert public["blood_collection"]["2026-08-20"] == {"is_enable": False, "cabins": []}
    assert public["blood_collection"]["2026-08-21"]["is_enable"] is True
    assert [c["cabin_key"] for c in public["blood_collection"]["2026-08-21"]["cabins"]] == [
        "blood_test_cabin_2"
    ]


def test_require_available_blood_collection_slot_rejects_disabled_date():
    slot_detail = {
        "blood_collection": {
            "2026-08-20": {
                "is_enable": False,
                "cabins": [
                    {
                        "cabin_name": "Blood Test Cabin 1",
                        "cabin_key": "blood_test_cabin_1",
                        "start_time": "09:00",
                        "end_time": "17:00",
                        "slot_duration": 30,
                        "capacity_per_slot": 6,
                        "breaks": [],
                        "is_active": True,
                    }
                ],
            }
        }
    }
    with pytest.raises(AppError) as err:
        require_available_blood_collection_slot(
            slot_detail,
            collection_date=date(2026, 8, 20),
            cabin_key="blood_test_cabin_1",
            slot_time=time(9, 0),
        )
    assert err.value.error_code == SLOT_UNAVAILABLE_CODE


def test_build_public_slot_detail_accepts_wrapped_and_legacy_shapes():
    legacy = {
        "blood_collection": {
            "2026-08-20": [
                {
                    "cabin_name": "Blood Test Cabin 1",
                    "cabin_key": "blood_test_cabin_1",
                    "start_time": "09:00",
                    "end_time": "10:00",
                    "slot_duration": 30,
                    "capacity_per_slot": 6,
                    "breaks": [],
                    "is_active": True,
                }
            ]
        }
    }
    wrapped = {
        "blood_collection": {
            "2026-08-20": {
                "is_enable": True,
                "cabins": legacy["blood_collection"]["2026-08-20"],
            }
        }
    }
    public_legacy = build_public_slot_detail(legacy)
    public_wrapped = build_public_slot_detail(wrapped)
    assert public_legacy == public_wrapped


def test_resolve_blood_collection_cabin_display_name():
    slot_detail = {
        "blood_collection": {
            "2026-08-20": [
                {
                    "cabin_name": "Blood Test Cabin 1",
                    "cabin_key": "blood_test_cabin_1",
                    "start_time": "09:00",
                    "end_time": "10:00",
                    "slot_duration": 30,
                    "capacity_per_slot": 6,
                    "breaks": [],
                    "is_active": True,
                }
            ]
        }
    }
    assert (
        resolve_blood_collection_cabin_display_name(
            slot_detail,
            collection_date=date(2026, 8, 20),
            cabin_key="blood_test_cabin_1",
        )
        == "Blood Test Cabin 1"
    )
    assert (
        resolve_blood_collection_cabin_display_name(
            slot_detail,
            collection_date=date(2026, 8, 20),
            cabin_key="missing_cabin",
        )
        == "missing_cabin"
    )
    assert (
        resolve_blood_collection_cabin_display_name(
            slot_detail,
            collection_date=date(2026, 8, 20),
            cabin_key=None,
        )
        is None
    )


def test_capacity_for_slot_uses_override_for_one_start_only():
    cabin = {
        "capacity_per_slot": 5,
        "slot_capacity_overrides": {"10:00": 7},
    }
    assert capacity_for_slot(cabin, time(9, 0)) == 5
    assert capacity_for_slot(cabin, time(10, 0)) == 7
    assert capacity_for_slot({"capacity_per_slot": 4}, time(9, 30)) == 4


def test_build_public_slot_detail_applies_per_slot_capacity_override():
    slot_detail = {
        "blood_collection": {
            "2026-08-20": [
                {
                    "cabin_name": "Blood Test Cabin 1",
                    "cabin_key": "blood_test_cabin_1",
                    "start_time": "09:00",
                    "end_time": "11:00",
                    "slot_duration": 30,
                    "capacity_per_slot": 5,
                    "slot_capacity_overrides": {"10:00": 7},
                    "breaks": [],
                    "is_active": True,
                }
            ]
        }
    }
    occupancy = {occupancy_key("blood_test_cabin_1", date(2026, 8, 20), time(10, 0)): 1}
    public = build_public_slot_detail(slot_detail, occupancy)
    slots = public["blood_collection"]["2026-08-20"]["cabins"][0]["available_slots"]
    assert slots == [
        {"slot": "09:00", "spot_left": 5},
        {"slot": "09:30", "spot_left": 5},
        {"slot": "10:00", "spot_left": 6},
        {"slot": "10:30", "spot_left": 5},
    ]


def test_build_cabin_slot_rows_includes_end_and_override():
    cabin = {
        "cabin_key": "blood_test_cabin_1",
        "start_time": "09:00",
        "end_time": "10:00",
        "slot_duration": 30,
        "capacity_per_slot": 4,
        "slot_capacity_overrides": {"09:00": 5},
        "breaks": [],
    }
    rows = build_cabin_slot_rows(
        cabin,
        slot_date=date(2026, 8, 20),
        occupancy={occupancy_key("blood_test_cabin_1", date(2026, 8, 20), time(9, 0)): 1},
    )
    assert rows == [
        {"slot": "09:00", "slot_end": "09:30", "capacity": 5, "spot_left": 4},
        {"slot": "09:30", "slot_end": "10:00", "capacity": 4, "spot_left": 4},
    ]
