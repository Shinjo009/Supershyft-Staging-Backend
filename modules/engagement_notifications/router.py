"""Engagement notifications HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from common.responses import success_response
from db.session import get_db
from modules.employee.dependencies import get_current_employee
from modules.employee.service import EmployeeContext
from modules.engagement_notifications.effective import list_effective_for_engagement
from modules.engagement_notifications.repository import EngagementNotificationsRepository
from modules.engagement_notifications.schemas import (
    EffectiveEngagementNotificationResponse,
    EngagementNotificationResponse,
    EngagementNotificationsUpsertRequest,
    configs_to_api,
)
from modules.notifications.events_catalog import get_event

router = APIRouter(tags=["engagement-notifications"])


def _get_repository() -> EngagementNotificationsRepository:
    return EngagementNotificationsRepository()


def _row_to_response(row) -> dict:
    catalog = get_event(row.event_code)
    return EngagementNotificationResponse(
        id=row.id,
        engagement_id=row.engagement_id,
        event_code=row.event_code,
        recipient_type=row.recipient_type,
        notification_services=configs_to_api(row.notification_services),
        event_display_name=catalog.event_name if catalog else row.event_code,
    ).model_dump()


@router.get("/engagements/{engagement_id}/notifications/effective")
async def get_effective_engagement_notifications(
    engagement_id: int,
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
):
    _ = employee
    rows = await list_effective_for_engagement(db, engagement_id)
    payload = [
        EffectiveEngagementNotificationResponse(
            engagement_id=row.engagement_id,
            event_code=row.event_code,
            recipient_type=row.recipient_type,
            notification_services=configs_to_api(row.notification_services),
            source=row.source,
            event_display_name=row.event_display_name,
            engagement_notification_id=row.engagement_notification_id,
        ).model_dump()
        for row in rows
    ]
    return success_response(payload)


@router.get("/engagements/{engagement_id}/notifications")
async def get_engagement_notifications(
    engagement_id: int,
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
    repo: EngagementNotificationsRepository = Depends(_get_repository),
):
    _ = employee
    rows = await repo.list_for_engagement(db, engagement_id)
    return success_response([_row_to_response(row) for row in rows])


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
    return success_response([_row_to_response(row) for row in rows])
