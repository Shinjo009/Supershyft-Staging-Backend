"""Pydantic schemas for server health monitoring.

Production health.db rows may have NULL overall_status (and occasionally
other nullable columns). These schemas coerce nulls so the API never 500s.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


def _derive_overall_status(ok_count: int, warn_count: int, crit_count: int) -> str:
    if crit_count > 0:
        return "CRITICAL"
    if warn_count > 0:
        return "WARNING"
    if ok_count > 0:
        return "HEALTHY"
    return "UNKNOWN"


class HealthRunRead(BaseModel):
    id: int
    run_at: str = ""
    ok_count: int = 0
    warn_count: int = 0
    crit_count: int = 0
    overall_status: str = "UNKNOWN"
    cpu_pct: float | None = None
    mem_pct: float | None = None
    storage_pct: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_nulls(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        row = dict(data)

        for key in ("ok_count", "warn_count", "crit_count"):
            if row.get(key) is None:
                row[key] = 0

        if row.get("run_at") is None:
            row["run_at"] = ""

        if row.get("overall_status") is None or str(row.get("overall_status", "")).strip() == "":
            row["overall_status"] = _derive_overall_status(
                int(row.get("ok_count") or 0),
                int(row.get("warn_count") or 0),
                int(row.get("crit_count") or 0),
            )
        else:
            row["overall_status"] = str(row["overall_status"]).strip().upper()

        for key in ("cpu_pct", "mem_pct", "storage_pct"):
            if key in row and row[key] is None:
                continue
            if key in row and row[key] == "":
                row[key] = None

        return row

    @field_validator("ok_count", "warn_count", "crit_count", mode="before")
    @classmethod
    def _int_or_zero(cls, value: Any) -> int:
        if value is None:
            return 0
        return int(value)

    @field_validator("cpu_pct", "mem_pct", "storage_pct", mode="before")
    @classmethod
    def _float_or_none(cls, value: Any) -> float | None:
        if value is None or value == "":
            return None
        return float(value)


class HealthCheckRead(BaseModel):
    id: int
    run_id: int
    category: str = ""
    status: str = "UNKNOWN"
    message: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_nulls(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        row = dict(data)
        if row.get("category") is None:
            row["category"] = ""
        if row.get("status") is None or str(row.get("status", "")).strip() == "":
            row["status"] = "UNKNOWN"
        else:
            row["status"] = str(row["status"]).strip().upper()
        if row.get("message") is None:
            row["message"] = ""
        return row


class HealthChecksByCategory(BaseModel):
    category: str
    checks: list[HealthCheckRead] = Field(default_factory=list)


class ServerHealthLatestMetricsRead(BaseModel):
    hostname: str
    cpu_usage: float
    memory_usage: float
    storage_usage: float
    load_1m: float
    cores: int
    timestamp: str


class ServerHealthCpuAlertRead(BaseModel):
    is_alerting: bool
    threshold_pct: float
    hostname: str | None = None
    last_alerted_at: str | None = None
    last_recovered_at: str | None = None


class ServerHealthCurrentRead(BaseModel):
    run: HealthRunRead
    checks_by_category: list[HealthChecksByCategory] = Field(default_factory=list)
    latest_metrics: ServerHealthLatestMetricsRead | None = None
    cpu_alert: ServerHealthCpuAlertRead | None = None


class ServerHealthMetricsIn(BaseModel):
    hostname: str = Field(..., min_length=1, max_length=255)
    cpu_usage: float = Field(..., ge=0, le=100)
    memory_usage: float = Field(..., ge=0, le=100)
    storage_usage: float = Field(..., ge=0, le=100)
    load_1m: float = Field(..., ge=0)
    cores: int = Field(..., ge=1)
    timestamp: datetime

    @field_validator("hostname", mode="before")
    @classmethod
    def _strip_hostname(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value
