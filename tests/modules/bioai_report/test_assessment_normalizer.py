"""Regression tests for production AssessmentPayload normalization crashes."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from modules.bioai_report.report_engine.builders.patient_builder import build_patient
from modules.bioai_report.report_engine.builders.report_builder import build_bioreport
from modules.bioai_report.report_engine.models.assessment import AssessmentPayload
from modules.bioai_report.report_engine.utils.assessment_normalizer import normalize_assessment
from modules.bioai_report.report_engine.utils.score_bands import clamp_score


def test_date_of_birth_date_object_does_not_raise():
    payload = normalize_assessment({"date_of_birth": date(1990, 4, 12), "diseases": []})
    assert payload.date_of_birth == "1990-04-12"
    assert build_patient(payload).date_of_birth == "1990-04-12"


def test_date_of_birth_datetime_is_iso_date():
    payload = normalize_assessment(
        {"date_of_birth": datetime(1995, 6, 15, 8, 30, tzinfo=timezone.utc), "diseases": []}
    )
    assert payload.date_of_birth == "1995-06-15"


def test_assessment_payload_accepts_date_directly():
    payload = AssessmentPayload(date_of_birth=date(2001, 4, 8))
    assert payload.date_of_birth == "2001-04-08"


def test_user_id_non_finite_and_non_numeric_are_dropped():
    inf_payload = normalize_assessment({"user_id": float("inf"), "diseases": []})
    nan_payload = normalize_assessment({"user_id": float("nan"), "diseases": []})
    uuid_payload = normalize_assessment(
        {"user_id": "550e8400-e29b-41d4-a716-446655440000", "diseases": []}
    )
    str_payload = normalize_assessment({"user_id": "12", "diseases": []})
    assert inf_payload.user_id is None
    assert nan_payload.user_id is None
    assert uuid_payload.user_id is None
    assert str_payload.user_id == 12


def test_weight_dict_decimal_and_non_finite():
    dict_payload = normalize_assessment({"weight": {"value": 70.5, "unit": "kg"}, "diseases": []})
    decimal_payload = normalize_assessment({"weight": Decimal("67.0"), "diseases": []})
    nan_payload = normalize_assessment({"weight": float("nan"), "diseases": []})
    inf_payload = normalize_assessment({"weight": float("inf"), "diseases": []})
    assert dict_payload.weight == 70.5
    assert decimal_payload.weight == 67
    assert nan_payload.weight is None
    assert inf_payload.weight is None


def test_gender_dict_does_not_crash_payload():
    payload = normalize_assessment({"gender": {"label": "female"}, "sex": 2, "diseases": []})
    assert payload.gender == "2"
    assert payload.sex == "2"


def test_messy_production_ihr_builds_json_safe_report():
    raw = {
        "id": 12345,
        "record": "ABC123",
        "user_id": float("inf"),
        "date_of_birth": date(1988, 3, 1),
        "gender": {"code": 1},
        "height": {"value": 170, "unit": "cm"},
        "weight": Decimal("72.4"),
        "age": float("nan"),
        "metabolic_score": 14,
        "diseases": [
            {
                "code": "obesity",
                "name": "Obesity",
                "risk_status": "High",
                "risk_score_scaled": float("nan"),
            },
            {
                "code": "hypertension",
                "name": "Hypertension",
                "risk_status": "Healthy",
                "risk_score_scaled": 16,
            },
        ],
    }
    report = build_bioreport(raw)
    dumped = report.to_dict()
    assert dumped["patient"]["date_of_birth"] == "1988-03-01"
    assert dumped["patient"]["height"] == 170.0
    assert dumped["patient"]["weight"] == 72.4
    assert dumped["patient"]["age"] is None
    assert dumped["patient"]["user_id"] is None
    assert "NaN" not in str(dumped)
    assert "Infinity" not in str(dumped)
    assert any(section["disease_id"] == "hypertension" for section in dumped["disease_sections"])


def test_clamp_score_non_finite_does_not_raise():
    assert clamp_score(float("nan")) == 0
    assert clamp_score(float("inf")) == 0
    assert clamp_score(67.4) == 67
