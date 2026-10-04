"""Inbound webhook HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from common.responses import success_response
from db.session import get_db
from modules.webhooks.dependencies import get_webhooks_receiver_service
from modules.webhooks.receiver.schemas import AuraeWebhookPayload, HealthiansWebhookPayload
from modules.webhooks.receiver.service import WebhooksReceiverService

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/healthians")
async def healthians_webhook(
    payload: HealthiansWebhookPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: WebhooksReceiverService = Depends(get_webhooks_receiver_service),
):
    result = await service.handle_healthians_webhook(
        db,
        payload=payload,
        api_endpoint_url=str(request.url.path),
    )
    await db.commit()
    return success_response(result)


@router.post("/orange-health")
async def orange_health_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: WebhooksReceiverService = Depends(get_webhooks_receiver_service),
    x_oh_signature: str | None = Header(None, alias="x-oh-signature"),
    x_oh_event_id: str | None = Header(None, alias="x-oh-event-id"),
):
    raw_body = await request.body()
    result = await service.handle_orange_health_webhook(
        db,
        raw_body=raw_body,
        api_endpoint_url=str(request.url.path),
        signature=x_oh_signature,
        x_oh_event_id=x_oh_event_id,
    )
    await db.commit()
    return success_response(result)


@router.post("/aurae")
async def aurae_webhook(
    payload: AuraeWebhookPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: WebhooksReceiverService = Depends(get_webhooks_receiver_service),
    x_api_key: str | None = Header(None, alias="x-api-key"),
):
    result = await service.handle_aurae_webhook(
        db,
        payload=payload,
        api_endpoint_url=str(request.url.path),
        api_key=x_api_key,
    )
    await db.commit()
    return success_response(result)
