"""Catalog and global notification event bindings HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from common.responses import success_response
from db.session import get_db
from modules.employee.dependencies import get_current_employee
from modules.employee.service import EmployeeContext
from modules.notifications.binding_schemas import (
    NotificationEventBindingCreateRequest,
    NotificationEventBindingUpdateRequest,
)
from modules.notifications.bindings_service import (
    NotificationCatalogService,
    NotificationEventBindingsService,
)

router = APIRouter(prefix="/notification-events", tags=["notification-events-catalog"])


def _catalog_service() -> NotificationCatalogService:
    return NotificationCatalogService()


def _bindings_service() -> NotificationEventBindingsService:
    return NotificationEventBindingsService()


@router.get("/catalog")
async def get_notification_events_catalog(
    employee: EmployeeContext = Depends(get_current_employee),
    catalog: NotificationCatalogService = Depends(_catalog_service),
):
    _ = employee
    data = catalog.catalog_response()
    return success_response(data.model_dump(mode="json"))


@router.get("/bindings")
async def list_notification_event_bindings(
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
    service: NotificationEventBindingsService = Depends(_bindings_service),
):
    _ = employee
    rows = await service.list_bindings(db)
    return success_response([row.model_dump(mode="json") for row in rows])


@router.post("/bindings")
async def create_notification_event_binding(
    payload: NotificationEventBindingCreateRequest,
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
    service: NotificationEventBindingsService = Depends(_bindings_service),
):
    _ = employee
    data = await service.create(db, payload)
    await db.commit()
    return success_response(data.model_dump(mode="json"))


@router.put("/bindings/{binding_id}")
async def update_notification_event_binding(
    binding_id: int,
    payload: NotificationEventBindingUpdateRequest,
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
    service: NotificationEventBindingsService = Depends(_bindings_service),
):
    _ = employee
    data = await service.update(db, binding_id, payload)
    await db.commit()
    return success_response(data.model_dump(mode="json"))


@router.delete("/bindings/{binding_id}")
async def delete_notification_event_binding(
    binding_id: int,
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
    service: NotificationEventBindingsService = Depends(_bindings_service),
):
    _ = employee
    await service.delete(db, binding_id)
    await db.commit()
    return success_response({"deleted": True})
