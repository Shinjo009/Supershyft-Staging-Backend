"""Unit tests for Healthians active zipcodes parsing."""

from modules.diagnostics.healthians.client import _parse_active_zipcodes_payload


def test_parse_active_zipcodes_payload():
    data = {
        "0": {"zipcode": "122505", "city_id": "23", "state_id": "26"},
        "1": {"zipcode": "122001", "city_id": "23", "state_id": "26"},
        "code": 200,
    }
    zips = _parse_active_zipcodes_payload(data)
    assert zips == {"122505", "122001"}
