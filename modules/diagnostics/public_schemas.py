"""Schemas for public diagnostic provider APIs (no auth)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from common.validation import (
    AddressText,
    CityStateCountry,
    OptionalLandmarkText,
    PinCode,
    PositiveIntId,
    ShortSafeText,
)


class PublicServiceabilityRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    address_line: AddressText
    landmark: OptionalLandmarkText = None
    city: CityStateCountry
    pincode: PinCode
    latitude: float | None = None
    longitude: float | None = None
    diagnostic_package_id: PositiveIntId | None = None


class PublicAvailableSlotsRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    slot_date: date
    diagnostic_package_id: PositiveIntId
    zone_id: str | None = Field(default=None, max_length=50)
    latitude: float | None = None
    longitude: float | None = None
    pincode: PinCode | None = None
    has_female_patient: bool = False


class PublicLockSlotRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    slot_id: str = Field(min_length=1, max_length=50)
    slot_date: date
    slot_time: ShortSafeText
    vendor_billing_user_id: str = Field(default="public", max_length=50)
    latitude: float | None = None
    longitude: float | None = None
    pincode: PinCode | None = None
    zone_id: str | None = Field(default=None, max_length=50)
