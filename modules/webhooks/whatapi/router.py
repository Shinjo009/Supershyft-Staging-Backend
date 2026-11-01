"""WhatAPI delivery webhook routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from common.responses import success_response
from db.session import get_db
from modules.webhooks.whatapi.service import WhatapiWebhookService

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def get_whatapi_webhook_service() -> WhatapiWebhookService:
    return WhatapiWebhookService()


@router.get("/whatapi")
async def whatapi_webhook_challenge(
    challenge: str | None = Query(None),
    challange: str | None = Query(None),
):
    token = (challenge or challange or "").strip()
    if not token:
        return PlainTextResponse("", status_code=400)
    return PlainTextResponse(token)


@router.post("/whatapi")
async def whatapi_webhook_delivery(
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: WhatapiWebhookService = Depends(get_whatapi_webhook_service),
):
    payload = await request.json()
    if not isinstance(payload, dict):
        payload = {"raw": payload}
    result = await service.handle_delivery_webhook(
        db,
        payload=payload,
        api_endpoint_url=str(request.url.path),
    )
    await db.commit()
    return success_response(result)
