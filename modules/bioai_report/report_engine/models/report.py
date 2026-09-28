"""BioReport output contract consumed by the frontend renderer.

Nested disease sections are render-ready PDF blocks. Knowledge-base field
names are never exposed to the frontend.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class PatientInfo(BaseModel):
    """Patient demographics and metabolic snapshot for the report."""

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

    @field_validator("date_of_birth", "assessment_date", mode="before")
    @classmethod
    def _coerce_date_strings(cls, value: Any, info: ValidationInfo) -> str | None:
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


class DiseaseHighlight(BaseModel):
    """Compact disease reference used in the executive summary."""

    model_config = ConfigDict(extra="ignore")

    disease_id: str
    title: str
    score: int
    risk: str
    band: str


class ExecutiveSummary(BaseModel):
    """Front-matter summary assembled before disease pages."""

    model_config = ConfigDict(extra="ignore")

    patient: PatientInfo
    assessment_date: str | None = None
    metabolic_score: float | int | None = None
    metabolic_age: float | int | None = None
    overall_status: str | None = None
    top_disease_risks: list[DiseaseHighlight] = Field(default_factory=list)
    top_health_strengths: list[DiseaseHighlight] = Field(default_factory=list)
    actionable_insights: list[str] = Field(default_factory=list)


class DiseaseCurrentStatus(BaseModel):
    """Score / risk block rendered at the top of a disease page."""

    model_config = ConfigDict(extra="ignore", ser_json_inf_nan="null")

    score: int
    risk: str
    band: str
    percentile: float | int | None = None
    healthy_percentile: float | int | None = None
    lifestyle_contribution: float | int | None = None
    interpretation: str = ""
    clinical_warning: str = ""


class DiseaseLifestyle(BaseModel):
    """Lifestyle tips and exercise recommendations for a disease page."""

    model_config = ConfigDict(extra="ignore")

    tips: list[str] = Field(default_factory=list)
    exercise: list[str] = Field(default_factory=list)


class DiseaseNutrition(BaseModel):
    """Nutrition block for a disease page."""

    model_config = ConfigDict(extra="ignore")

    recommendations: list[str] = Field(default_factory=list)
    foods_to_include: list[str] = Field(default_factory=list)
    foods_to_avoid: list[str] = Field(default_factory=list)


class DiseaseMonitoring(BaseModel):
    """Monitoring recommendations for a disease page."""

    model_config = ConfigDict(extra="ignore")

    recommendations: list[str] = Field(default_factory=list)


class DiseaseResultFactors(BaseModel):
    """Score-selected factors explaining what may be affecting disease results."""

    model_config = ConfigDict(extra="ignore")

    title: str = "What could be affecting your results?"
    factors: list[str] = Field(default_factory=list)


class DiseaseSection(BaseModel):
    """Render-ready disease page — nested blocks match PDF sections."""

    model_config = ConfigDict(extra="ignore")

    disease_id: str
    title: str
    overview: str
    current_status: DiseaseCurrentStatus
    lifestyle: DiseaseLifestyle
    nutrition: DiseaseNutrition
    monitoring: DiseaseMonitoring
    positive_takeaway: str = ""
    result_factors: DiseaseResultFactors

    @property
    def score(self) -> int:
        """Convenience accessor used for sorting and executive-summary highlights."""
        return self.current_status.score

    @property
    def risk(self) -> str:
        return self.current_status.risk

    @property
    def band(self) -> str:
        return self.current_status.band


class ReportMetadata(BaseModel):
    """Engine provenance for the assembled report."""

    model_config = ConfigDict(extra="ignore")

    record_id: str
    engine_version: str
    kb_version: str | None = None
    template_version: str
    generated_at: str | None = None
    disease_count: int = 0
    source: str = "metsights"


class BioReport(BaseModel):
    """Final JSON contract between the content engine and the frontend."""

    model_config = ConfigDict(extra="ignore", ser_json_inf_nan="null")

    patient: PatientInfo
    executive_summary: ExecutiveSummary
    disease_sections: list[DiseaseSection] = Field(default_factory=list)
    report_metadata: ReportMetadata

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
