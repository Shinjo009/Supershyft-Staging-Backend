"""Tests for POST/GET /webhooks/whatapi."""

from __future__ import annotations

import pytest

from modules.notifications.models import Notification, NotificationService
from modules.users.models import User


@pytest.mark.asyncio
async def test_whatapi_webhook_get_challenge(async_client):
    response = await async_client.get("/webhooks/whatapi", params={"challenge": "verify-me"})
    assert response.status_code == 200
    assert response.text == "verify-me"


@pytest.mark.asyncio
async def test_whatapi_webhook_post_updates_notification_by_queue_id(async_client, test_db_session):
    test_db_session.add(User(user_id=99001, age=30, phone="9900100000", status="active"))
    test_db_session.add(
        NotificationService(
            service_key="whatapi-otp-test",
            display_name="OTP WA",
            channel="whatsapp",
            webhook_path="whatapi-otp",
            is_active=True,
        )
    )
    await test_db_session.flush()
    notif = Notification(
        service_key="whatapi-otp-test",
        status="queued",
        channel="whatsapp",
        user={"user_ids": [99001]},
        queue_id="test-queue-99001",
        message="queued",
    )
    test_db_session.add(notif)
    await test_db_session.commit()
    await test_db_session.refresh(notif)

    payload = {
        "message": {
            "queue_id": "test-queue-99001",
            "message_status": "delivered",
        }
    }
    response = await async_client.post("/webhooks/whatapi", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["notification_id"] == notif.notification_id
    assert data["status"] == "delivered"

    from sqlalchemy import select

    notif_id = notif.notification_id
    result = await test_db_session.execute(
        select(Notification).where(Notification.notification_id == notif_id)
    )
    refreshed = result.scalar_one()
    assert refreshed.status == "delivered"
    assert refreshed.completed_at is not None
