"""Unit tests for health-span-index waist measurement extraction."""

from __future__ import annotations

from modules.reports.service import ReportsService


def test_normalize_waist_unit():
    assert ReportsService._normalize_waist_unit("0") == "cm"
    assert ReportsService._normalize_waist_unit("cm") == "cm"
    assert ReportsService._normalize_waist_unit("1") == "in"
    assert ReportsService._normalize_waist_unit("in") == "in"
    assert ReportsService._normalize_waist_unit("inch") == "in"
    assert ReportsService._normalize_waist_unit("inches") == "in"
    assert ReportsService._normalize_waist_unit(None) is None
    assert ReportsService._normalize_waist_unit("mm") is None


def test_extract_waist_measurement_inches():
    lookup = {"waist_circumference": {"value": 30, "unit": "1"}}
    waist = ReportsService._extract_waist_measurement(lookup)
    assert waist is not None
    assert waist.value == 30
    assert waist.unit == "in"


def test_extract_waist_measurement_cm():
    lookup = {"waist_circumference": {"value": 76, "unit": "0"}}
    waist = ReportsService._extract_waist_measurement(lookup)
    assert waist is not None
    assert waist.value == 76
    assert waist.unit == "cm"


def test_extract_waist_measurement_cm_label():
    lookup = {"waist_circumference": {"value": 80.5, "unit": "cm"}}
    waist = ReportsService._extract_waist_measurement(lookup)
    assert waist is not None
    assert waist.value == 80.5
    assert waist.unit == "cm"


def test_extract_waist_measurement_missing():
    assert ReportsService._extract_waist_measurement({}) is None
    assert ReportsService._extract_waist_measurement({"waist_circumference": {"unit": "1"}}) is None


_IDEAL_WAIST_RAW = {
    "low": 80.0,
    "high": 94.0,
    "unit": "cm",
    "cm": {"low": 80.0, "high": 94.0},
    "in": {"low": 31.5, "high": 37.0},
    "input_unit": None,
}


def test_map_ideal_waist_matches_inches_measurement():
    ideal = ReportsService._map_ideal_waist(_IDEAL_WAIST_RAW, preferred_unit="in")
    assert ideal is not None
    assert ideal.low == 31.5
    assert ideal.high == 37.0
    assert ideal.unit == "in"


def test_map_ideal_waist_matches_cm_measurement():
    ideal = ReportsService._map_ideal_waist(_IDEAL_WAIST_RAW, preferred_unit="cm")
    assert ideal is not None
    assert ideal.low == 80.0
    assert ideal.high == 94.0
    assert ideal.unit == "cm"


def test_map_ideal_waist_falls_back_to_input_unit():
    raw = {**_IDEAL_WAIST_RAW, "input_unit": "in"}
    ideal = ReportsService._map_ideal_waist(raw, preferred_unit=None)
    assert ideal is not None
    assert ideal.unit == "in"
    assert ideal.low == 31.5
    assert ideal.high == 37.0


def test_map_ideal_waist_falls_back_to_top_level():
    ideal = ReportsService._map_ideal_waist(
        {"low": 80.0, "high": 94.0, "unit": "cm"},
        preferred_unit="in",
    )
    assert ideal is not None
    assert ideal.low == 80.0
    assert ideal.high == 94.0
    assert ideal.unit == "cm"
