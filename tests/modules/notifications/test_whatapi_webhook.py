"""Tests for WhatAPI inbound webhook routes."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from modules.notifications.models import Notification


@pytest.mark.asyncio
async def test_whatapi_webhook_get_echo_challenge(async_client):
    response = await async_client.get(
        "/webhooks/whatapi",
        params={"echo": "true", "challange": "OFS1EE"},
    )
    assert response.status_code == 200
    assert response.text == "OFS1EE"


@pytest.mark.asyncio
async def test_whatapi_webhook_post_updates_by_queue_id(async_client, test_db_session):
    await test_db_session.execute(
        text(
            "INSERT INTO notification_services "
            "(service_key, display_name, channel, webhook_path, is_active, "
            "require_blood_report_url, require_bio_ai_report_url, require_participant_detail) "
            "VALUES ('wa-q-test', 'WA', 'whatsapp', '/wa-q-test', true, false, false, false) "
            "ON CONFLICT (service_key) DO NOTHING"
        )
    )
    await test_db_session.commit()

    test_db_session.add(
        Notification(
            service_key="wa-q-test",
            status="queued",
            channel="whatsapp",
            user={"user_ids": [1]},
            queue_id="queue-test-123",
            message="queued",
        )
    )
    await test_db_session.commit()

    response = await async_client.post(
        "/webhooks/whatapi",
        json={"queue_id": "queue-test-123", "status": "delivered"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["updated"] is True

    row = await test_db_session.get(Notification, 1)
    # notification_id may not be 1 — re-query
    from sqlalchemy import select

    result = await test_db_session.execute(
        select(Notification).where(Notification.queue_id == "queue-test-123")
    )
    notification = result.scalar_one()
    assert notification.status == "delivered"
    assert notification.completed_at is not None


@pytest.mark.asyncio
async def test_whatapi_webhook_post_without_queue_id_no_update(async_client, test_db_session):
    response = await async_client.post(
        "/webhooks/whatapi",
        json={"event": "incoming", "type": "template"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["updated"] is False
