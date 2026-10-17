from __future__ import annotations

from modules.engagements.participant_report_flags import (
    _apply_ihr_row,
    default_participant_report_flags,
    merge_report_flags_into_participant_row,
)


def test_fitprint_json_does_not_count_as_bio_ai_values():
    flags = default_participant_report_flags()
    fitprint_reports = {
        "assessment": {"name": "FitPrint Full", "assessment_type": "FitPrint Full"},
        "fitness_specification": {"score": 1},
    }
    _apply_ihr_row(
        flags,
        report_url=None,
        reports=fitprint_reports,
        assessment_type_code="7",
    )
    assert flags["has_fitprint_values"] is True
    assert flags["has_bio_ai_values"] is False
    assert flags["has_bio_ai_json"] is False


def test_basic_json_counts_as_bio_ai_values_not_fitprint():
    flags = default_participant_report_flags()
    bio_reports = {
        "metabolic_age": 30,
        "diseases": [],
    }
    _apply_ihr_row(
        flags,
        report_url="https://example.com/report.pdf",
        reports=bio_reports,
        assessment_type_code="1",
    )
    assert flags["has_bio_ai_report"] is True
    assert flags["has_bio_ai_values"] is True
    assert flags["has_fitprint_values"] is False
    assert flags["bio_ai_report_url"] == "https://example.com/report.pdf"


def test_merge_report_flags_sets_booking_id_from_row():
    row = {"user_id": 1, "booking_id": "12345"}
    flags = default_participant_report_flags()
    flags["has_bio_ai_report"] = True
    merge_report_flags_into_participant_row(row, flags)
    assert row["has_booking_id"] is True
    assert row["has_bio_ai_report"] is True


def test_fitprint_report_url_sets_fitprint_report_only():
    flags = default_participant_report_flags()
    _apply_ihr_row(
        flags,
        report_url="https://example.com/fitprint.pdf",
        reports=None,
        assessment_type_code="7",
    )
    assert flags["has_fitprint_report"] is True
    assert flags["has_bio_ai_report"] is False
