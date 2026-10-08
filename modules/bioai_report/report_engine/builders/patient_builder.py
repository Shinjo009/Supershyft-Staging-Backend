"""Build the patient object for BioReport output."""

from __future__ import annotations

import math

from modules.bioai_report.report_engine.models.assessment import AssessmentPayload
from modules.bioai_report.report_engine.models.report import PatientInfo
from modules.users.gender_labels import normalize_gender_label


def _one_decimal(value: float | int | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, 1)


def _as_user_id(value: float | int | None) -> int | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    try:
        return int(number)
    except (OverflowError, ValueError):
        return None


def build_patient(assessment: AssessmentPayload) -> PatientInfo:
    """Map assessment fields into the patient section of the BioReport."""
    gender = normalize_gender_label(assessment.gender or assessment.sex)
    return PatientInfo(
        record_id=assessment.record_id,
        name=assessment.name,
        age=assessment.age,
        sex=gender,
        gender=gender,
        date_of_birth=assessment.date_of_birth,
        height=_one_decimal(assessment.height),
        weight=assessment.weight,
        bmi=assessment.bmi,
        profile_id=assessment.profile_id,
        user_id=_as_user_id(assessment.user_id),
        metabolic_age=assessment.metabolic_age,
        metabolic_score=assessment.metabolic_score,
        metabolic_health_status=assessment.metabolic_health_status,
        assessment_code=assessment.assessment_code,
        assessment_date=assessment.assessment_date or assessment.created_at,
    )
