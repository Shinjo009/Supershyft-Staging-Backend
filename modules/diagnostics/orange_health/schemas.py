"""Pydantic schemas for Orange Health partner API payloads."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class OrangeHealthServiceabilityQuery(BaseModel):
    latitude: float
    longitude: float
    request_date: str = Field(..., description="YYYY-MM-DD")


class OrangeHealthCreateOrderPatient(BaseModel):
    partner_reference_id: Optional[str] = None
    patient_name: str
    patient_phone: Optional[str] = None
    age: str
    gender: str
    packages: Optional[list[dict[str, str]]] = None
    tests: Optional[list[dict[str, str]]] = None


class OrangeHealthCreateOrderRequest(BaseModel):
    address: str
    location: Optional[dict[str, str]] = None
    primary_patient_name: str
    primary_patient_number: str
    slot_datetime: Optional[str] = None
    payment_type: str = "paid_by_group"
    partner_notes: str = ""
    patient_details: list[dict[str, Any]]
