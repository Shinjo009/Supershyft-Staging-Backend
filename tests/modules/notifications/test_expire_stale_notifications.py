"""Tests for expiring stale pending notifications."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from modules.notifications.expire_stale import expire_stale_notifications
from modules.notifications.models import Notification
from modules.notifications.repository import NotificationsRepository


async def _seed_service(test_db_session, *, service_key: str) -> None:
    await test_db_session.execute(
        text(
            "INSERT INTO notification_services "
            "(service_key, display_name, channel, template_name, email_subject, email_body, is_active, require_blood_report_url, require_bio_ai_report_url, require_participant_detail) "
            "VALUES (:sk, :dn, 'email', NULL, 'Test', 'Test', true, false, false, false) "
            "ON CONFLICT (service_key) DO NOTHING"
        ),
        {"sk": service_key, "dn": service_key},
    )
    await test_db_session.commit()


async def _create_pending(
    test_db_session,
    *,
    service_key: str,
    dispatched_at: datetime,
    completed_at: datetime | None = None,
    message: str = "Workflow was started",
    queue_id: str | None = None,
) -> Notification:
    notification = Notification(
        service_key=service_key,
        status="pending",
        channel="email",
        user={"user_ids": [42]},
        engagement_id=None,
        message=message,
        queue_id=queue_id,
        dispatched_at=dispatched_at,
        completed_at=completed_at,
    )
    test_db_session.add(notification)
    await test_db_session.commit()
    await test_db_session.refresh(notification)
    return notification


@pytest.mark.asyncio
async def test_recent_pending_is_not_expired(test_db_session):
    await _seed_service(test_db_session, service_key="stale-recent-svc")
    notification = await _create_pending(
        test_db_session,
        service_key="stale-recent-svc",
        dispatched_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )

    result = await expire_stale_notifications(
        test_db_session,
        repository=NotificationsRepository(),
        timeout_hours=2,
        dry_run=False,
    )
    await test_db_session.commit()
    await test_db_session.refresh(notification)

    assert result["expired"] == 0
    assert notification.status == "pending"


@pytest.mark.asyncio
async def test_old_pending_is_expired(test_db_session):
    await _seed_service(test_db_session, service_key="stale-old-svc")
    notification = await _create_pending(
        test_db_session,
        service_key="stale-old-svc",
        dispatched_at=datetime.now(timezone.utc) - timedelta(hours=5),
    )

    result = await expire_stale_notifications(
        test_db_session,
        repository=NotificationsRepository(),
        timeout_hours=2,
        dry_run=False,
    )
    await test_db_session.commit()
    await test_db_session.refresh(notification)

    assert result["expired"] == 1
    assert notification.status == "failed"
    assert "timeout" in (notification.message or "").lower()


@pytest.mark.asyncio
async def test_old_pending_with_completed_at_is_healed_to_sent(test_db_session):
    await _seed_service(test_db_session, service_key="stale-heal-svc")
    notification = await _create_pending(
        test_db_session,
        service_key="stale-heal-svc",
        dispatched_at=datetime.now(timezone.utc) - timedelta(hours=5),
        completed_at=datetime.now(timezone.utc) - timedelta(hours=5),
        message="WhatsApp delivered (sent)",
        queue_id="heal-queue-1",
    )

    result = await expire_stale_notifications(
        test_db_session,
        repository=NotificationsRepository(),
        timeout_hours=2,
        dry_run=False,
    )
    await test_db_session.commit()
    await test_db_session.refresh(notification)

    assert result["expired"] == 0
    assert result["healed"] == 1
    assert notification.status == "sent"
    assert "healed" in (notification.message or "").lower()
