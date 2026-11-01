"""Tests for pretest blood-collection reminder dispatch."""

from __future__ import annotations

from datetime import date, time

import pytest
from sqlalchemy import text

from modules.engagements.repository import EngagementsRepository
from modules.notifications.pretest_reminders import (
    dispatch_pretest_reminders,
    format_blood_collection_slot,
)
from modules.notifications.repository import NotificationsRepository
from modules.notifications.service import NotificationsService
from modules.users.models import User
from tests.modules.notifications.notification_test_seeds import (
    patch_direct_delivery_success,
    upsert_engagement_notification,
    upsert_notification_service,
)

PRETEST_WHATSAPP_KEY = "pretest-whatsapp-1-1-v1"
PRETEST_EMAIL_KEY = "pretest-email-1-1-v1"
DEFAULT_PRETEST_KEYS = f"{PRETEST_WHATSAPP_KEY},{PRETEST_EMAIL_KEY}"


async def _seed_dependencies(test_db_session) -> None:
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, status) "
            "VALUES (1, 'PKG1', 'Test Package', 1) ON CONFLICT (package_id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, package_name, diagnostic_provider, status) "
            "VALUES (1, 'Test Diagnostic', 'test_provider', 1) ON CONFLICT (diagnostic_package_id) DO NOTHING"
        )
    )
    for service_key, channel in (
        (PRETEST_WHATSAPP_KEY, "whatsapp"),
        (PRETEST_EMAIL_KEY, "email"),
        ("custom-pretest-only", "email"),
    ):
        await upsert_notification_service(
            test_db_session,
            service_key=service_key,
            channel=channel,
            hint="session_details",
            email_subject="Pretest" if channel == "email" else None,
            email_body="Reminder {{user.first_name}}" if channel == "email" else None,
        )
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_types (code, display_name, is_active) "
            "VALUES ('bio_ai', 'BioAI', true) "
            "ON CONFLICT (code) DO UPDATE SET is_active = true"
        )
    )
    await test_db_session.commit()


async def _bind_pretest_services(
    test_db_session,
    *,
    engagement_id: int,
    service_keys: str = DEFAULT_PRETEST_KEYS,
) -> None:
    await upsert_engagement_notification(
        test_db_session,
        engagement_id=engagement_id,
        event_code="pretest_guidelines",
        notification_services=service_keys,
        recipient_type="participant",
    )


async def _insert_engagement(
    test_db_session,
    *,
    engagement_id: int,
    engagement_code: str,
    status: str,
    bind_services: bool = True,
    service_keys: str = DEFAULT_PRETEST_KEYS,
) -> None:
    await test_db_session.execute(
        text(
            "INSERT INTO engagements "
            "(engagement_id, engagement_name, engagement_code, engagement_type, assessment_package_id, "
            "diagnostic_package_id, city, slot_duration, start_date, end_date, status, organization_id) "
            f"VALUES ({engagement_id}, 'Camp {engagement_id}', '{engagement_code}', "
            "(SELECT id FROM engagement_types WHERE code = 'bio_ai'), 1, 1, 'BLR', 20, "
            f"'2026-06-01', '2026-06-30', '{status}', NULL)"
        )
    )
    if bind_services:
        await _bind_pretest_services(
            test_db_session, engagement_id=engagement_id, service_keys=service_keys
        )


async def _insert_participant(
    test_db_session,
    *,
    engagement_id: int,
    user_id: int,
    engagement_date: str,
    slot_start_time: str | None,
) -> None:
    test_db_session.add(
        User(user_id=user_id, age=30, phone=f"{user_id}000000000", status="active")
    )
    await test_db_session.flush()
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_participants "
            "(engagement_id, user_id, engagement_date, slot_start_time, booked_by_user_id) "
            "VALUES (:eid, :uid, :ed, :slot, :uid)"
        ),
        {
            "eid": engagement_id,
            "uid": user_id,
            "ed": date.fromisoformat(engagement_date),
            "slot": time.fromisoformat(slot_start_time) if slot_start_time else None,
        },
    )


def _services():
    notifications_repository = NotificationsRepository()
    return (
        NotificationsService(notifications_repository),
        EngagementsRepository(),
    )


def test_format_blood_collection_slot():
    assert format_blood_collection_slot(time(8, 30)) == "8:30 AM"
    assert format_blood_collection_slot(time(14, 0)) == "2:00 PM"
    assert format_blood_collection_slot(None) == ""


@pytest.mark.asyncio
async def test_pretest_reminders_all_participants(test_db_session, monkeypatch):
    await _seed_dependencies(test_db_session)
    await _insert_engagement(
        test_db_session, engagement_id=9601, engagement_code="ENG9601", status="running"
    )
    collection_date = "2026-06-02"
    as_of = date(2026, 6, 1)
    await _insert_participant(
        test_db_session,
        engagement_id=9601,
        user_id=96011,
        engagement_date=collection_date,
        slot_start_time="08:30:00",
    )
    await _insert_participant(
        test_db_session,
        engagement_id=9601,
        user_id=96012,
        engagement_date=collection_date,
        slot_start_time="09:00:00",
    )
    await _insert_participant(
        test_db_session,
        engagement_id=9601,
        user_id=96013,
        engagement_date=collection_date,
        slot_start_time="10:00:00",
    )
    await test_db_session.commit()

    patch_direct_delivery_success(monkeypatch)

    notifications_service, engagements_repository = _services()
    result = await dispatch_pretest_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=False,
    )
    await test_db_session.commit()

    assert result["matched"] == 3
    assert result["sent"] == 3
    assert result["skipped"] == 0
    assert result["failed"] == 0

    notification_count = (
        await test_db_session.execute(text("SELECT COUNT(*) FROM notifications"))
    ).scalar_one()
    assert notification_count == 6


@pytest.mark.asyncio
async def test_pretest_reminders_excludes_completed_engagements(test_db_session, monkeypatch):
    await _seed_dependencies(test_db_session)
    await _insert_engagement(
        test_db_session, engagement_id=9603, engagement_code="ENG9603", status="completed"
    )
    collection_date = "2026-06-02"
    as_of = date(2026, 6, 1)
    await _insert_participant(
        test_db_session,
        engagement_id=9603,
        user_id=96031,
        engagement_date=collection_date,
        slot_start_time="08:00:00",
    )
    await test_db_session.commit()

    patch_direct_delivery_success(monkeypatch)

    notifications_service, engagements_repository = _services()
    result = await dispatch_pretest_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=False,
    )
    await test_db_session.commit()

    assert result["matched"] == 0
    notification_count = (
        await test_db_session.execute(text("SELECT COUNT(*) FROM notifications"))
    ).scalar_one()
    assert notification_count == 0


@pytest.mark.asyncio
async def test_pretest_reminders_includes_scheduled_engagements(test_db_session, monkeypatch):
    await _seed_dependencies(test_db_session)
    await _insert_engagement(
        test_db_session, engagement_id=9605, engagement_code="ENG9605", status="scheduled"
    )
    collection_date = "2026-06-02"
    as_of = date(2026, 6, 1)
    await _insert_participant(
        test_db_session,
        engagement_id=9605,
        user_id=96051,
        engagement_date=collection_date,
        slot_start_time="08:00:00",
    )
    await test_db_session.commit()

    patch_direct_delivery_success(monkeypatch)

    notifications_service, engagements_repository = _services()
    result = await dispatch_pretest_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=False,
    )
    await test_db_session.commit()

    assert result["matched"] == 1
    assert result["sent"] == 1
    assert result["skipped"] == 0
    assert result["failed"] == 0
    notification_count = (
        await test_db_session.execute(text("SELECT COUNT(*) FROM notifications"))
    ).scalar_one()
    assert notification_count == 2


@pytest.mark.asyncio
async def test_pretest_reminders_dry_run_does_not_dispatch(test_db_session, monkeypatch):
    await _seed_dependencies(test_db_session)
    await _insert_engagement(
        test_db_session, engagement_id=9604, engagement_code="ENG9604", status="running"
    )
    collection_date = "2026-06-02"
    as_of = date(2026, 6, 1)
    await _insert_participant(
        test_db_session,
        engagement_id=9604,
        user_id=96041,
        engagement_date=collection_date,
        slot_start_time="08:00:00",
    )
    await test_db_session.commit()

    patch_direct_delivery_success(monkeypatch)

    notifications_service, engagements_repository = _services()
    result = await dispatch_pretest_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=True,
    )
    await test_db_session.commit()

    assert result["matched"] == 1
    assert result["dry_run"] is True

    notification_count = (
        await test_db_session.execute(text("SELECT COUNT(*) FROM notifications"))
    ).scalar_one()
    assert notification_count == 0


@pytest.mark.asyncio
async def test_pretest_reminders_one_user_id_per_dispatch(test_db_session, monkeypatch):
    await _seed_dependencies(test_db_session)
    await _insert_engagement(
        test_db_session, engagement_id=9606, engagement_code="ENG9606", status="running"
    )
    collection_date = "2026-06-02"
    as_of = date(2026, 6, 1)
    await _insert_participant(
        test_db_session,
        engagement_id=9606,
        user_id=96061,
        engagement_date=collection_date,
        slot_start_time="07:00:00",
    )
    await test_db_session.commit()

    patch_direct_delivery_success(monkeypatch)

    notifications_service, engagements_repository = _services()
    await dispatch_pretest_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=False,
    )
    await test_db_session.commit()

    notification_count = (
        await test_db_session.execute(text("SELECT COUNT(*) FROM notifications"))
    ).scalar_one()
    assert notification_count == 2


@pytest.mark.asyncio
async def test_pretest_reminders_skips_when_no_keys_configured(test_db_session, monkeypatch):
    await _seed_dependencies(test_db_session)
    await _insert_engagement(
        test_db_session,
        engagement_id=9607,
        engagement_code="ENG9607",
        status="running",
        bind_services=False,
    )
    collection_date = "2026-06-02"
    as_of = date(2026, 6, 1)
    await _insert_participant(
        test_db_session,
        engagement_id=9607,
        user_id=96071,
        engagement_date=collection_date,
        slot_start_time="08:00:00",
    )
    await test_db_session.commit()

    patch_direct_delivery_success(monkeypatch)

    notifications_service, engagements_repository = _services()
    result = await dispatch_pretest_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=False,
    )
    await test_db_session.commit()

    assert result["matched"] == 0
    notification_count = (
        await test_db_session.execute(text("SELECT COUNT(*) FROM notifications"))
    ).scalar_one()
    assert notification_count == 0


@pytest.mark.asyncio
async def test_pretest_reminders_single_custom_key(test_db_session, monkeypatch):
    await _seed_dependencies(test_db_session)
    await _insert_engagement(
        test_db_session,
        engagement_id=9608,
        engagement_code="ENG9608",
        status="running",
        service_keys="custom-pretest-only",
    )
    collection_date = "2026-06-02"
    as_of = date(2026, 6, 1)
    await _insert_participant(
        test_db_session,
        engagement_id=9608,
        user_id=96081,
        engagement_date=collection_date,
        slot_start_time="09:15:00",
    )
    await test_db_session.commit()

    patch_direct_delivery_success(monkeypatch)

    notifications_service, engagements_repository = _services()
    result = await dispatch_pretest_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=False,
    )
    await test_db_session.commit()

    assert result["matched"] == 1
    assert result["sent"] == 1

    rows = (
        await test_db_session.execute(text("SELECT service_key FROM notifications"))
    ).all()
    assert len(rows) == 1
    assert rows[0].service_key == "custom-pretest-only"


@pytest.mark.asyncio
async def test_pretest_reminders_skips_missing_slot(test_db_session, monkeypatch):
    await _seed_dependencies(test_db_session)
    await _insert_engagement(
        test_db_session, engagement_id=9609, engagement_code="ENG9609", status="running"
    )
    collection_date = "2026-06-02"
    as_of = date(2026, 6, 1)
    await _insert_participant(
        test_db_session,
        engagement_id=9609,
        user_id=96091,
        engagement_date=collection_date,
        slot_start_time=None,
    )
    await test_db_session.commit()

    patch_direct_delivery_success(monkeypatch)

    notifications_service, engagements_repository = _services()
    result = await dispatch_pretest_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=False,
    )
    await test_db_session.commit()

    assert result["matched"] == 1
    assert result["sent"] == 0
    assert result["skipped"] == 1
    notification_count = (
        await test_db_session.execute(text("SELECT COUNT(*) FROM notifications"))
    ).scalar_one()
    assert notification_count == 0
    assert result["details"][0]["reason"] == "missing slot_start_time for session_details"
