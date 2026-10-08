"""Pydantic schemas for export log APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from common.validation import reject_unsafe_strings

ExportType = Literal["participants", "database_backup", "contact_reveal"]
ExportFormat = Literal["csv", "xlsx"]
ExportSourceKind = Literal["engagement", "organization", "camp", "system", "user"]


class ExportLogCreateRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)
    export_type: ExportType
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("reason")
    @classmethod
    def _clean_reason(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if len(cleaned) < 3:
            raise ValueError("Reason must be at least 3 characters")
        return reject_unsafe_strings(cleaned, max_len=500)

    @field_validator("details")
    @classmethod
    def _clean_details(cls, value: dict[str, Any] | None) -> dict[str, Any]:
        if value is None:
            return {}
        cleaned = reject_unsafe_strings(value, max_len=500)
        if not isinstance(cleaned, dict):
            raise ValueError("details must be an object")
        return cleaned

    @model_validator(mode="after")
    def _validate_details_shape(self) -> "ExportLogCreateRequest":
        if not self.reason.strip():
            raise ValueError("Reason is required")

        details = dict(self.details or {})
        export_format = details.get("export_format")
        source_kind = details.get("source_kind")
        source_id = details.get("source_id")
        exported = details.get("exported_participants", [])

        if self.export_type == "contact_reveal":
            if export_format not in (None,):
                raise ValueError("export_format must be null for contact_reveal")
            details["export_format"] = None
        else:
            if export_format not in ("csv", "xlsx"):
                raise ValueError("export_format must be csv or xlsx")
            details["export_format"] = export_format

        allowed_kinds = {"engagement", "organization", "camp", "system", "user"}
        if source_kind not in allowed_kinds:
            raise ValueError("source_kind is required")
        details["source_kind"] = source_kind

        if source_id is None or source_id == "":
            details["source_id"] = None
        else:
            sid = str(source_id).strip()
            if len(sid) > 64:
                raise ValueError("source_id too long")
            details["source_id"] = sid or None

        if exported is None:
            exported = []
        if not isinstance(exported, list):
            raise ValueError("exported_participants must be an array")
        normalized: list[int] = []
        for item in exported:
            try:
                normalized.append(int(item))
            except (TypeError, ValueError) as exc:
                raise ValueError("exported_participants must be integers") from exc
        details["exported_participants"] = normalized

        self.details = details
        return self


class RevealContactRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def _clean_reason(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if len(cleaned) < 3:
            raise ValueError("Reason must be at least 3 characters")
        return reject_unsafe_strings(cleaned, max_len=500)


class ExportLogItem(BaseModel):
    export_log_id: int
    employee_id: int
    employee_name: str
    employee_role: str
    reason: str
    export_type: str
    details: dict[str, Any] | None = None
    created_at: datetime
