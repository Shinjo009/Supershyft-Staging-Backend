"""Notifications module Pydantic schemas."""

from __future__ import annotations

from datetime import date

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from common.validation import (
    OptionalSafeDisplayName,
    OptionalSafeText,
    OtpCode,
    PositiveIntId,
    SafeDisplayName,
    SafeText,
    ServiceKey,
    SlugKey,
    validate_nested_strings,
)


class SessionDetails(BaseModel):
    want: bool
    date: date
    slot: str
    expert_type: SlugKey
    cabin: str | None = None


class PrepareReportsRequest(BaseModel):
    user_id: PositiveIntId
    require_blood_report_url: bool = False
    require_bio_ai_report_url: bool = False


def _drop_empty_participant_detail_strings(value: Any) -> Any:
    """Remove blank strings so optional UI fields (e.g. engagement) do not fail SafeText validation."""
    if isinstance(value, dict):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            pruned = _drop_empty_participant_detail_strings(item)
            if isinstance(pruned, str) and not pruned.strip():
                continue
            cleaned[key] = pruned
        return cleaned
    if isinstance(value, list):
        return [_drop_empty_participant_detail_strings(item) for item in value]
    return value


class DispatchRequest(BaseModel):
    service_key: ServiceKey
    user_ids: list[PositiveIntId] = Field(..., min_length=1)
    engagement_id: PositiveIntId | None = None
    assessment_instance_id: PositiveIntId | None = None
    participant_details: dict | None = None
    otp: OtpCode | None = None
    session_details: SessionDetails | None = None
    session_details_by_user_id: dict[int, SessionDetails] | None = None
    external_link: str | None = None

    @model_validator(mode="after")
    def sanitize_participant_details(self) -> "DispatchRequest":
        if self.participant_details is not None:
            pruned = _drop_empty_participant_detail_strings(self.participant_details)
            if isinstance(pruned, dict):
                self.participant_details = pruned or None
            if self.participant_details:
                validate_nested_strings(self.participant_details)
        return self

    @field_validator("external_link")
    @classmethod
    def validate_external_link(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        from urllib.parse import urlparse

        parsed = urlparse(stripped)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("external_link must be a valid http(s) URL")
        return stripped

    @field_validator("session_details_by_user_id", mode="before")
    @classmethod
    def _coerce_session_details_user_ids(cls, value: object) -> object:
        if value is None or not isinstance(value, dict):
            return value
        return {int(user_id): details for user_id, details in value.items()}


class CallbackRequest(BaseModel):
    notification_id: int
    status: str = Field(..., pattern=r"^(sent|failed)$")
    message: OptionalSafeText = None


class NotificationServiceCreate(BaseModel):
    service_key: ServiceKey
    display_name: SafeDisplayName
    channel: str = Field(..., pattern=r"^(email|whatsapp)$")
    is_active: bool = True
    template_name: str | None = None
    template_variables: list[Any] | None = None
    email_subject: str | None = None
    email_body: str | None = None
    email_html: str | None = None


class BulkDeleteNotificationsRequest(BaseModel):
    notification_ids: list[PositiveIntId] = Field(..., min_length=1, max_length=500)


class NotificationServiceUpdate(BaseModel):
    display_name: OptionalSafeDisplayName = None
    channel: str | None = Field(None, pattern=r"^(email|whatsapp)$")
    is_active: bool | None = None
    template_name: str | None = None
    template_variables: list[Any] | None = None
    email_subject: str | None = None
    email_body: str | None = None
    email_html: str | None = None


class EventBindingServiceItem(BaseModel):
    service_key: str = Field(min_length=1)
    external_link: str | None = None

    @field_validator("external_link")
    @classmethod
    def validate_external_link(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        from urllib.parse import urlparse

        parsed = urlparse(stripped)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("external_link must be a valid http(s) URL")
        return stripped


class EventBindingCreateRequest(BaseModel):
    event_code: SlugKey
    event_name: SafeDisplayName
    recipient_type: SafeText
    notification_services: list[EventBindingServiceItem] = Field(..., min_length=1)


class EventBindingUpdateRequest(BaseModel):
    event_name: OptionalSafeDisplayName = None
    recipient_type: OptionalSafeText = None
    notification_services: list[EventBindingServiceItem] | None = None


class EventBindingResponse(BaseModel):
    id: int
    event_code: str
    event_name: str
    recipient_type: str
    notification_services: list[dict]
    created_at: str | None = None
