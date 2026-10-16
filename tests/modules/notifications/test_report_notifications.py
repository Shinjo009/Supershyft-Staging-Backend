"""Tests for send_report_notifications (per-service commit, no rollback)."""

from __future__ import annotations

from datetime import date
import pytest
from sqlalchemy import func, select, text

from core.exceptions import AppError
from modules.engagement_notifications.service_config import NotificationServiceConfigItem
from modules.engagements.models import Engagement
from modules.notifications.models import Notification
from modules.notifications.report_notifications import send_report_notifications
from modules.notifications.repository import NotificationsRepository
from modules.notifications.service import NotificationsService
from modules.users.models import User


async def _seed_base(
    test_db_session,
    *,
    user_id: int = 88001,
    engagement_id: int = 88001,
) -> None:
    await test_db_session.execute(
        text(
            "INSERT INTO notification_services "
            "(service_key, display_name, channel, webhook_path, is_active, "
            "require_blood_report_url, require_bio_ai_report_url, require_participant_detail) "
            "VALUES "
            "('rn-whatsapp', 'RN WhatsApp', 'whatsapp', 'wa-hook', true, false, false, false), "
            "('rn-email-blood', 'RN Email', 'email', 'email-hook', true, true, true, false) "
            "ON CONFLICT (service_key) DO UPDATE SET "
            "require_blood_report_url = EXCLUDED.require_blood_report_url, "
            "require_bio_ai_report_url = EXCLUDED.require_bio_ai_report_url"
        )
    )
    test_db_session.add(
        User(
            user_id=user_id,
            first_name="Test",
            last_name="User",
            phone="8800100000",
            age=30,
            status="active",
        )
    )
    test_db_session.add(
        Engagement(
            engagement_id=engagement_id,
            engagement_name="RN Test Engagement",
            engagement_code=f"ENG-RN-{engagement_id}",
            engagement_type=None,
            assessment_package_id=1,
            diagnostic_package_id=1,
            city="BLR",
            slot_duration=20,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 30),
            status="running",
        )
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_send_report_notifications_commits_whatsapp_when_email_raises(
    test_db_session,
):
    await _seed_base(test_db_session)
    user_id = 88001
    engagement_id = 88001
    instance_id = 88001
    details: list[dict] = []

    svc = NotificationsService(repository=NotificationsRepository())

    async def _dispatch(db, *, payload, triggered_by_user_id=None):
        if payload.service_key == "rn-email-blood":
            raise AppError(
                status_code=400,
                error_code="INVALID_INPUT",
                message=f"BioAI report URL not available for user_id={user_id}",
            )
        db.add(
            Notification(
                service_key=payload.service_key,
                status="sent",
                channel="whatsapp",
                user={"user_ids": payload.user_ids},
                engagement_id=engagement_id,
                message="mock sent",
            )
        )
        return {"status": "sent"}

    svc.dispatch = _dispatch  # type: ignore[method-assign]

    configs = [
        NotificationServiceConfigItem(service_key="rn-whatsapp", external_link=None),
        NotificationServiceConfigItem(service_key="rn-email-blood", external_link=None),
    ]
    sent = await send_report_notifications(
        test_db_session,
        notifications_service=svc,
        service_configs=configs,
        user_id=user_id,
        engagement_id=engagement_id,
        assessment_instance_id=instance_id,
        details=details,
    )

    assert sent == 1
    rows = (
        await test_db_session.execute(
            select(Notification).where(
                Notification.engagement_id == engagement_id,
                Notification.service_key == "rn-whatsapp",
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    email_rows = (
        await test_db_session.execute(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.engagement_id == engagement_id,
                Notification.service_key == "rn-email-blood",
            )
        )
    ).scalar_one()
    assert email_rows == 0
    assert any(d.get("action") == "skipped" for d in details)


@pytest.mark.asyncio
async def test_send_report_notifications_preskips_blood_service_without_pdf(
    test_db_session,
):
    await _seed_base(test_db_session, user_id=88002, engagement_id=88002)
    user_id = 88002
    engagement_id = 88002
    details: list[dict] = []
    dispatch_calls: list[str] = []

    svc = NotificationsService(repository=NotificationsRepository())

    async def _dispatch(db, *, payload, triggered_by_user_id=None):
        dispatch_calls.append(payload.service_key)
        db.add(
            Notification(
                service_key=payload.service_key,
                status="sent",
                channel="whatsapp",
                user={"user_ids": payload.user_ids},
                engagement_id=engagement_id,
                message="mock",
            )
        )
        return {"status": "sent"}

    svc.dispatch = _dispatch  # type: ignore[method-assign]

    configs = [
        NotificationServiceConfigItem(service_key="rn-whatsapp", external_link=None),
        NotificationServiceConfigItem(service_key="rn-email-blood", external_link=None),
    ]
    sent = await send_report_notifications(
        test_db_session,
        notifications_service=svc,
        service_configs=configs,
        user_id=user_id,
        engagement_id=engagement_id,
        assessment_instance_id=88002,
        details=details,
    )

    assert sent == 1
    assert dispatch_calls == ["rn-whatsapp"]
    assert any(
        "Blood report URL not available" in (d.get("reason") or "")
        for d in details
    )
    wa_count = (
        await test_db_session.execute(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.engagement_id == engagement_id,
                Notification.service_key == "rn-whatsapp",
            )
        )
    ).scalar_one()
    assert wa_count == 1


@pytest.mark.asyncio
async def test_send_report_notifications_dedup_skips_second_run(test_db_session):
    await _seed_base(test_db_session, user_id=88003, engagement_id=88003)
    user_id = 88003
    engagement_id = 88003
    details: list[dict] = []

    svc = NotificationsService(repository=NotificationsRepository())

    async def _dispatch(db, *, payload, triggered_by_user_id=None):
        db.add(
            Notification(
                service_key=payload.service_key,
                status="sent",
                channel="whatsapp",
                user={"user_ids": payload.user_ids},
                engagement_id=engagement_id,
                message="mock",
            )
        )
        return {"status": "sent"}

    svc.dispatch = _dispatch  # type: ignore[method-assign]

    configs = [
        NotificationServiceConfigItem(service_key="rn-whatsapp", external_link=None),
    ]

    sent1 = await send_report_notifications(
        test_db_session,
        notifications_service=svc,
        service_configs=configs,
        user_id=user_id,
        engagement_id=engagement_id,
        assessment_instance_id=88003,
        details=details,
    )
    assert sent1 == 1

    details2: list[dict] = []
    sent2 = await send_report_notifications(
        test_db_session,
        notifications_service=svc,
        service_configs=configs,
        user_id=user_id,
        engagement_id=engagement_id,
        assessment_instance_id=88003,
        details=details2,
    )
    assert sent2 == 0
    assert any("already sent" in (d.get("reason") or "") for d in details2)
