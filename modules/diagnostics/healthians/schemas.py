"""Pydantic schemas for Healthians integration."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class HealthiansConstituentsRequest(BaseModel):
    external_package_code: str = Field(..., min_length=1)


class HealthiansConstituent(BaseModel):
    id: str
    name: str


class HealthiansConstituentsResponse(BaseModel):
    constituents: list[HealthiansConstituent]
    package_name: Optional[str] = None
