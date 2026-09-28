"""Normalize raw MetSights / assessment JSON into AssessmentPayload."""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from modules.bioai_report.report_engine.models.assessment import (
    AssessmentDisease,
    AssessmentPayload,
)


def _unwrap_data(raw: dict[str, Any]) -> dict[str, Any]:
    """Prefer nested ``data`` when top-level scored fields are absent."""
    if "diseases" in raw or "metabolic_score" in raw or "metabolic_age" in raw:
        return raw
    nested = raw.get("data")
    if isinstance(nested, dict):
        return nested
    return raw


def _as_optional_str(value: Any) -> str | None:
    """Coerce scalars / dates to a trimmed string. Never raise."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(value, (dict, list, tuple, set)):
        return None
    try:
        text = str(value).strip()
    except Exception:
        return None
    return text or None


def _as_optional_date_str(value: Any) -> str | None:
    """Coerce a date / datetime / ISO string to ``YYYY-MM-DD``. Never raise."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = _as_optional_str(value)
    if text is None:
        return None
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return text


def _as_optional_number(value: Any) -> float | int | None:
    """Coerce a numeric scalar. Rejects NaN/Inf and never raises."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, dict):
        value = value.get("value", value.get("amount"))
    if isinstance(value, Decimal):
        try:
            value = float(value)
        except (InvalidOperation, OverflowError, ValueError):
            return None
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except (OverflowError, ValueError, TypeError):
            return None
        if not math.isfinite(number):
            return None
        if number.is_integer():
            return int(number)
        return number
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        if not math.isfinite(number):
            return None
        if number.is_integer():
            return int(number)
        return number
    return None


def _as_optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    number = _as_optional_number(value)
    if number is None:
        return None
    try:
        return int(number)
    except (OverflowError, ValueError, TypeError):
        return None


def _parse_diseases(raw_diseases: Any) -> list[AssessmentDisease]:
    if not isinstance(raw_diseases, list):
        return []
    diseases: list[AssessmentDisease] = []
    for entry in raw_diseases:
        if not isinstance(entry, dict):
            continue
        code = _as_optional_str(entry.get("code"))
        if not code:
            continue
        try:
            diseases.append(
                AssessmentDisease(
                    code=code,
                    name=_as_optional_str(entry.get("name")),
                    risk_status=_as_optional_str(entry.get("risk_status")),
                    risk_score_scaled=_as_optional_number(entry.get("risk_score_scaled")),
                    healthy_percentile=_as_optional_number(entry.get("healthy_percentile")),
                    lifestyle_contribution=_as_optional_number(
                        entry.get("lifestyle_contribution")
                    ),
                    disease_percentile=_as_optional_number(entry.get("disease_percentile")),
                    risk_status_message=_as_optional_str(entry.get("risk_status_message")),
                    lifestyle_contribution_message=_as_optional_str(
                        entry.get("lifestyle_contribution_message")
                    ),
                )
            )
        except (ValidationError, OverflowError, ValueError, TypeError):
            continue
    return diseases


def normalize_assessment(
    raw: dict[str, Any],
    *,
    record_id: str | None = None,
) -> AssessmentPayload:
    """Convert MetSights report JSON into a typed AssessmentPayload."""
    if not isinstance(raw, dict):
        raise TypeError("assessment payload must be a dict")

    body = _unwrap_data(raw)
    resolved_record_id = (
        _as_optional_str(record_id)
        or _as_optional_str(body.get("record_id"))
        or _as_optional_str(body.get("id"))
        or _as_optional_str(raw.get("record_id"))
    )

    sex = _as_optional_str(body.get("sex"))
    gender = _as_optional_str(body.get("gender")) or sex
    if sex is None and gender is not None:
        sex = gender

    user_id = _as_optional_int(
        body.get("user_id") if body.get("user_id") is not None else raw.get("user_id")
    )

    try:
        return AssessmentPayload(
            record_id=resolved_record_id,
            name=_as_optional_str(body.get("name")),
            age=_as_optional_number(body.get("age")),
            sex=sex,
            gender=gender,
            date_of_birth=_as_optional_date_str(body.get("date_of_birth")),
            height=_as_optional_number(body.get("height")),
            weight=_as_optional_number(body.get("weight")),
            bmi=_as_optional_number(body.get("bmi")),
            profile_id=_as_optional_str(body.get("profile_id")),
            user_id=user_id,
            metabolic_age=_as_optional_number(body.get("metabolic_age")),
            metabolic_score=_as_optional_number(body.get("metabolic_score")),
            metabolic_health_status=_as_optional_str(body.get("metabolic_health_status")),
            assessment_code=_as_optional_str(body.get("assessment_code")),
            assessment_date=_as_optional_str(body.get("assessment_date"))
            or _as_optional_str(body.get("created_at")),
            created_at=_as_optional_str(body.get("created_at")),
            diseases=_parse_diseases(body.get("diseases")),
            raw=raw,
        )
    except ValidationError as exc:
        raise ValueError("assessment payload is invalid") from exc
