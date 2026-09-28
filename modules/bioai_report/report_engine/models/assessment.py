"""Assessment payload models (normalized from MetSights report JSON)."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class AssessmentDisease(BaseModel):
    """One disease entry from the assessment / MetSights report."""

    model_config = ConfigDict(extra="ignore")

    code: str
    name: str | None = None
    risk_status: str | None = None
    risk_score_scaled: float | int | None = None
    healthy_percentile: float | int | None = None
    lifestyle_contribution: float | int | None = None
    disease_percentile: float | int | None = None
    risk_status_message: str | None = None
    lifestyle_contribution_message: str | None = None


class AssessmentPayload(BaseModel):
    """Normalized assessment JSON used by report builders."""

    model_config = ConfigDict(extra="ignore", ser_json_inf_nan="null")

    record_id: str | None = None
    name: str | None = None
    age: float | int | None = None
    sex: str | None = None
    gender: str | None = None
    date_of_birth: str | None = None
    height: float | int | None = None
    weight: float | int | None = None
    bmi: float | int | None = None
    profile_id: str | None = None
    user_id: int | None = None
    metabolic_age: float | int | None = None
    metabolic_score: float | int | None = None
    metabolic_health_status: str | None = None
    assessment_code: str | None = None
    assessment_date: str | None = None
    created_at: str | None = None
    diseases: list[AssessmentDisease] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @field_validator("date_of_birth", "assessment_date", "created_at", mode="before")
    @classmethod
    def _coerce_date_strings(cls, value: Any, info: ValidationInfo) -> str | None:
        """``users.date_of_birth`` is a Date; Pydantic rejects date objects for str fields."""
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, datetime):
            if info.field_name == "date_of_birth":
                return value.date().isoformat()
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, (dict, list, tuple, set, bytes)):
            return None
        text = str(value).strip()
        return text or None

    @field_validator("user_id", mode="before")
    @classmethod
    def _coerce_user_id(cls, value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        try:
            return int(number)
        except (OverflowError, ValueError):
            return None
