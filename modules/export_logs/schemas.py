"""Pydantic schemas for export log APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from common.validation import reject_unsafe_strings

ExportType = Literal["participants", "database_backup"]
ExportFormat = Literal["csv", "xlsx"]
ExportSourceKind = Literal["engagement", "organization", "camp", "system"]


class ExportLogCreateRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)
    export_type: ExportType
    export_format: ExportFormat
    source_kind: ExportSourceKind
    source_id: Optional[str] = Field(default=None, max_length=64)
    row_count: Optional[int] = Field(default=None, ge=0)
    details: Optional[dict[str, Any]] = None

    @field_validator("reason")
    @classmethod
    def _clean_reason(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if len(cleaned) < 3:
            raise ValueError("Reason must be at least 3 characters")
        return reject_unsafe_strings(cleaned, max_len=500)

    @field_validator("source_id")
    @classmethod
    def _clean_source_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("details")
    @classmethod
    def _clean_details(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        return reject_unsafe_strings(value, max_len=500)

    @model_validator(mode="after")
    def _reason_not_blank(self) -> "ExportLogCreateRequest":
        if not self.reason.strip():
            raise ValueError("Reason is required")
        return self


class ExportLogItem(BaseModel):
    export_log_id: int
    employee_id: int | None = None
    partner_id: int | None = None
    actor_name: str
    actor_role: str
    reason: str
    export_type: str
    export_format: str
    source_kind: str
    source_id: str | None = None
    row_count: int | None = None
    details: dict[str, Any] | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime
