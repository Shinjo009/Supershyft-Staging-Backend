from datetime import date

from modules.diagnostics.redcliffe.booking_helpers import (
    extract_redcliffe_booking_id,
    slim_redcliffe_slots,
)


def test_slim_redcliffe_slots_maps_stm_id():
    raw = [
        {
            "id": 27,
            "format_12_hrs": {"start_time": "03:30 PM", "end_time": "04:30 PM"},
        }
    ]
    slim = slim_redcliffe_slots(raw, collection_date=date(2026, 4, 15))
    assert slim[0]["stm_id"] == "27"
    assert slim[0]["slot_time"] == "03:30 PM"
    assert slim[0]["slot_date"] == "2026-04-15"


def test_extract_redcliffe_booking_id_prefers_confirm():
    assert extract_redcliffe_booking_id({"booking_id": 99}) == "99"
    assert extract_redcliffe_booking_id({"pk": 88}) == "88"