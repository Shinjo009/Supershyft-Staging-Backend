"""Pydantic schemas for catalog and global notification event bindings."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from common.validation import SafeDisplayName, ServiceKey


class CustomContactsPayload(BaseModel):
    phones: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)


class NotificationEventBindingCreateRequest(BaseModel):
    event_code: str = Field(min_length=1, max_length=128)
    recipient_type: str = Field(min_length=1, max_length=64)
    notification_services: list[ServiceKey] = Field(..., min_length=1)
    custom_contacts: CustomContactsPayload | None = None
    filters: dict | None = None
    is_active: bool = True


class NotificationEventBindingUpdateRequest(BaseModel):
    event_name: SafeDisplayName | None = None
    notification_services: list[ServiceKey] | None = Field(default=None, min_length=1)
    custom_contacts: CustomContactsPayload | None = None
    filters: dict | None = None
    is_active: bool | None = None


class NotificationEventBindingResponse(BaseModel):
    id: int
    event_code: str
    event_name: str
    recipient_type: str
    notification_services: list[str]
    custom_contacts: CustomContactsPayload | None = None
    filters: dict | None = None
    is_active: bool
    created_at: datetime


class CatalogEventRead(BaseModel):
    event_code: str
    event_name: str
    group: str
    is_live_today: bool
    trigger_description: str
    recipient_types: list[str]
    variable_bags: list[str]
    extra_variables: list[str]
    nested_under: str | None = None
    legacy_event_code: str | None = None
    legacy_service_keys: list[str] | None = None


class CatalogGroupRead(BaseModel):
    prefix: str
    events: list[CatalogEventRead]


class CatalogResponse(BaseModel):
    groups: list[CatalogGroupRead]
    shared_variable_bags: dict[str, list[str]]
    legacy_event_code_map: dict[str, str]
