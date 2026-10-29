"""Pydantic schemas for user onboarding payload fields."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from common.validation import OptionalSafeDisplayName, OptionalSlugKey, SlugKey

UserOnboardingPayloadSectionLiteral = Literal["personal_information", "address", "schedule"]
UserOnboardingPayloadInputTypeLiteral = Literal["number", "text", "json"]


class UserOnboardingPayloadFieldCreateRequest(BaseModel):
    payload_key: SlugKey
    display_name: OptionalSafeDisplayName = None
    section: UserOnboardingPayloadSectionLiteral
    input_type: UserOnboardingPayloadInputTypeLiteral


class UserOnboardingPayloadFieldUpdateRequest(BaseModel):
    payload_key: OptionalSlugKey = None
    display_name: OptionalSafeDisplayName = None
    section: UserOnboardingPayloadSectionLiteral | None = None
    input_type: UserOnboardingPayloadInputTypeLiteral | None = None


class CampOnboardingPayloadUpdateRequest(BaseModel):
    onboarding_payload: dict[str, Any] = Field(default_factory=dict)
