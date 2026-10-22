"""Engagement notifications HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from common.responses import success_response
from core.exceptions import AppError
from db.session import get_db
from modules.employee.dependencies import get_current_employee
from modules.employee.service import EmployeeContext
from modules.engagement_notifications.repository import (
    EngagementNotificationsRepository,
    list_default_bindings_for_engagement_type,
)
from modules.engagement_notifications.schemas import (
    EngagementNotificationResponse,
    EngagementNotificationsUpsertRequest,
    NotificationDefaultResponse,
    NotificationDefaultsUpsertRequest,
    configs_to_api,
)
from modules.notifications.events_catalog import get_catalog_event

router = APIRouter(tags=["engagement-notifications"])


def _get_repository() -> EngagementNotificationsRepository:
    return EngagementNotificationsRepository()


def _display_name_for_event_code(event_code: str) -> str | None:
    catalog = get_catalog_event(event_code)
    return catalog.event_name if catalog else None


@router.get("/engagements/{engagement_id}/notifications")
async def get_engagement_notifications(
    engagement_id: int,
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
    repo: EngagementNotificationsRepository = Depends(_get_repository),
):
    _ = employee
    rows = await repo.list_for_engagement(db, engagement_id)
    data = [
        EngagementNotificationResponse(
            id=row.id,
            engagement_id=row.engagement_id,
            event_code=row.event_code,
            recipient_type=row.recipient_type,
            notification_services=configs_to_api(row.notification_services),
            event_display_name=_display_name_for_event_code(row.event_code),
        ).model_dump()
        for row in rows
    ]
    return success_response(data)


@router.put("/engagements/{engagement_id}/notifications")
async def upsert_engagement_notifications(
    engagement_id: int,
    payload: EngagementNotificationsUpsertRequest,
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
    repo: EngagementNotificationsRepository = Depends(_get_repository),
):
    _ = employee
    items = [item.model_dump() for item in payload.notifications]
    await repo.upsert_for_engagement(db, engagement_id, items)
    await db.commit()
    rows = await repo.list_for_engagement(db, engagement_id)
    data = [
        EngagementNotificationResponse(
            id=row.id,
            engagement_id=row.engagement_id,
            event_code=row.event_code,
            recipient_type=row.recipient_type,
            notification_services=configs_to_api(row.notification_services),
            event_display_name=_display_name_for_event_code(row.event_code),
        ).model_dump()
        for row in rows
    ]
    return success_response(data)


@router.get("/platform-settings/engagement-notification-defaults")
async def get_notification_defaults(
    engagement_type_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
):
    _ = employee
    rows = await list_default_bindings_for_engagement_type(db, engagement_type_id)
    data = [
        NotificationDefaultResponse(
            id=0,
            engagement_type_id=engagement_type_id,
            event_code=row["event_code"],
            recipient_type=row["recipient_type"],
            notification_services=configs_to_api(row["notification_services"]),
            event_display_name=_display_name_for_event_code(row["event_code"]),
        ).model_dump()
        for row in rows
    ]
    return success_response(data)


@router.put("/platform-settings/engagement-notification-defaults")
async def upsert_notification_defaults(
    payload: NotificationDefaultsUpsertRequest,
    employee: EmployeeContext = Depends(get_current_employee),
):
    _ = employee
    _ = payload
    raise AppError(
        status_code=410,
        error_code="GONE",
        message=(
            "Engagement notification defaults are managed via "
            "GET/PUT /notifications/event-bindings (platform-wide per event_code)."
        ),
    )
