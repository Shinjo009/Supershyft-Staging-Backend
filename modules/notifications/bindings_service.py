"""Catalog read and global notification event bindings service."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppError
from modules.engagement_notifications.service_config import validate_notification_service_configs
from modules.notifications.binding_schemas import (
    CatalogEventRead,
    CatalogGroupRead,
    CatalogResponse,
    CustomContactsPayload,
    NotificationEventBindingCreateRequest,
    NotificationEventBindingResponse,
    NotificationEventBindingUpdateRequest,
)
from modules.notifications.bindings_repository import NotificationEventBindingsRepository
from modules.notifications.events_catalog import (
    ALL_EVENTS,
    EventGroup,
    LEGACY_EVENT_CODE_MAP,
    SHARED_VARIABLE_BAGS,
    get_event,
    recipient_types_allowed,
)
from modules.notifications.models import NotificationEventBinding


class NotificationCatalogService:
    def catalog_response(self) -> CatalogResponse:
        groups: list[CatalogGroupRead] = []
        for group in EventGroup:
            events = [
                CatalogEventRead(
                    event_code=e.event_code,
                    event_name=e.event_name,
                    group=e.group,
                    is_live_today=e.is_live_today,
                    trigger_description=e.trigger_description,
                    recipient_types=e.recipient_types,
                    variable_bags=e.variable_bags,
                    extra_variables=e.extra_variables,
                    nested_under=e.nested_under,
                    legacy_event_code=e.legacy_event_code,
                    legacy_service_keys=e.legacy_service_keys,
                )
                for e in ALL_EVENTS
                if e.group == group.value
            ]
            groups.append(CatalogGroupRead(prefix=group.value, events=events))
        return CatalogResponse(
            groups=groups,
            shared_variable_bags=SHARED_VARIABLE_BAGS,
            legacy_event_code_map=dict(LEGACY_EVENT_CODE_MAP),
        )


class NotificationEventBindingsService:
    def __init__(self, repository: NotificationEventBindingsRepository | None = None):
        self._repository = repository or NotificationEventBindingsRepository()

    def _validate_binding_payload(
        self,
        *,
        event_code: str,
        recipient_type: str,
        custom_contacts: CustomContactsPayload | None,
    ) -> None:
        if get_event(event_code) is None:
            raise AppError(
                status_code=400,
                error_code="INVALID_INPUT",
                message=f"Unknown event_code '{event_code}'",
            )
        allowed = recipient_types_allowed(event_code)
        if recipient_type not in allowed:
            raise AppError(
                status_code=400,
                error_code="INVALID_INPUT",
                message=(
                    f"recipient_type '{recipient_type}' is not allowed for event '{event_code}'"
                ),
            )
        if recipient_type == "custom":
            if custom_contacts is None or (
                not custom_contacts.phones and not custom_contacts.emails
            ):
                raise AppError(
                    status_code=400,
                    error_code="INVALID_INPUT",
                    message="custom_contacts with phones or emails is required when recipient_type=custom",
                )

    def _to_response(self, obj: NotificationEventBinding) -> NotificationEventBindingResponse:
        custom = None
        if obj.custom_contacts and isinstance(obj.custom_contacts, dict):
            custom = CustomContactsPayload(
                phones=list(obj.custom_contacts.get("phones") or []),
                emails=list(obj.custom_contacts.get("emails") or []),
            )
        services = obj.notification_services
        if isinstance(services, list):
            service_keys = [str(s) for s in services]
        else:
            service_keys = []
        return NotificationEventBindingResponse(
            id=obj.id,
            event_code=obj.event_code,
            event_name=obj.event_name,
            recipient_type=obj.recipient_type,
            notification_services=service_keys,
            custom_contacts=custom,
            filters=obj.filters if isinstance(obj.filters, dict) else None,
            is_active=obj.is_active,
            created_at=obj.created_at,
        )

    async def list_bindings(self, db: AsyncSession) -> list[NotificationEventBindingResponse]:
        rows = await self._repository.list_all(db)
        return [self._to_response(row) for row in rows]

    async def create(
        self,
        db: AsyncSession,
        payload: NotificationEventBindingCreateRequest,
    ) -> NotificationEventBindingResponse:
        self._validate_binding_payload(
            event_code=payload.event_code,
            recipient_type=payload.recipient_type,
            custom_contacts=payload.custom_contacts,
        )
        catalog_event = get_event(payload.event_code)
        assert catalog_event is not None
        existing = await self._repository.get_by_code_and_recipient(
            db,
            event_code=payload.event_code,
            recipient_type=payload.recipient_type,
        )
        if existing is not None:
            raise AppError(
                status_code=409,
                error_code="DUPLICATE_BINDING",
                message=(
                    f"Binding already exists for event '{payload.event_code}' "
                    f"and recipient '{payload.recipient_type}'"
                ),
            )
        await validate_notification_service_configs(
            db,
            notification_services=[
                {"service_key": key} for key in payload.notification_services
            ],
        )
        custom_dict = (
            payload.custom_contacts.model_dump(mode="json") if payload.custom_contacts else None
        )
        obj = await self._repository.create(
            db,
            event_code=payload.event_code,
            event_name=catalog_event.event_name,
            recipient_type=payload.recipient_type,
            notification_services=list(payload.notification_services),
            custom_contacts=custom_dict,
            filters=payload.filters,
            is_active=payload.is_active,
        )
        return self._to_response(obj)

    async def update(
        self,
        db: AsyncSession,
        binding_id: int,
        payload: NotificationEventBindingUpdateRequest,
    ) -> NotificationEventBindingResponse:
        obj = await self._repository.get_by_id(db, binding_id)
        if obj is None:
            raise AppError(status_code=404, error_code="NOT_FOUND", message="Binding not found")

        effective_custom = payload.custom_contacts
        if effective_custom is None and obj.recipient_type == "custom":
            if obj.custom_contacts and isinstance(obj.custom_contacts, dict):
                effective_custom = CustomContactsPayload(
                    phones=list(obj.custom_contacts.get("phones") or []),
                    emails=list(obj.custom_contacts.get("emails") or []),
                )

        self._validate_binding_payload(
            event_code=obj.event_code,
            recipient_type=obj.recipient_type,
            custom_contacts=effective_custom,
        )

        if payload.notification_services is not None:
            await validate_notification_service_configs(
                db,
                notification_services=[
                    {"service_key": key} for key in payload.notification_services
                ],
            )

        custom_kw: dict | None | object = ...
        if payload.custom_contacts is not None:
            custom_kw = payload.custom_contacts.model_dump(mode="json")

        filters_kw: dict | None | object = ...
        if payload.filters is not None:
            filters_kw = payload.filters

        updated = await self._repository.update(
            db,
            binding_id,
            event_name=payload.event_name,
            notification_services=(
                list(payload.notification_services)
                if payload.notification_services is not None
                else None
            ),
            custom_contacts=custom_kw,
            filters=filters_kw,
            is_active=payload.is_active,
        )
        assert updated is not None
        return self._to_response(updated)

    async def delete(self, db: AsyncSession, binding_id: int) -> None:
        success = await self._repository.delete(db, binding_id)
        if not success:
            raise AppError(status_code=404, error_code="NOT_FOUND", message="Binding not found")
