"""Deprecated: use GET /notifications/events/catalog and /notifications/event-bindings."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core.exceptions import AppError
from modules.employee.dependencies import get_current_employee
from modules.employee.service import EmployeeContext

router = APIRouter(prefix="/notification-events", tags=["notification-events"])

_DEPRECATION = (
    "Auto notification events CRUD was removed. "
    "Use GET /notifications/events/catalog and /notifications/event-bindings instead."
)


def _gone():
    raise AppError(status_code=410, error_code="GONE", message=_DEPRECATION)


@router.get("")
async def list_notification_events(
    employee: EmployeeContext = Depends(get_current_employee),
):
    _ = employee
    _gone()


@router.get("/{event_id}")
async def get_notification_event(
    event_id: int,
    employee: EmployeeContext = Depends(get_current_employee),
):
    _ = employee
    _ = event_id
    _gone()


@router.post("", status_code=201)
async def create_notification_event(
    employee: EmployeeContext = Depends(get_current_employee),
):
    _ = employee
    _gone()


@router.put("/{event_id}")
async def update_notification_event(
    event_id: int,
    employee: EmployeeContext = Depends(get_current_employee),
):
    _ = employee
    _ = event_id
    _gone()


@router.delete("/{event_id}")
async def delete_notification_event(
    event_id: int,
    employee: EmployeeContext = Depends(get_current_employee),
):
    _ = employee
    _ = event_id
    _gone()
