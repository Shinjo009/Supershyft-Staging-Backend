"""Unit tests for family-onboard Diwali gift notifications."""

from __future__ import annotations

from datetime import date
import pytest
from sqlalchemy import select, text

from modules.engagements.models import Engagement
from modules.notifications.family_onboard_gift_notify import (
    RECEIVER_EMAIL_KEY,
    RECEIVER_WHATSAPP_KEY,
    SENDER_EMAIL_KEY,
    SENDER_WHATSAPP_KEY,
    _is_booker_plus_alias_email,
    notify_family_onboard_gift,
)
from modules.notifications.repository import NotificationsRepository
from modules.notifications.service import NotificationsService
from modules.users.models import User

_KEYS = (
    SENDER_WHATSAPP_KEY,
    SENDER_EMAIL_KEY,
    RECEIVER_WHATSAPP_KEY,
    RECEIVER_EMAIL_KEY,
)


async def _seed_diagnostic_package(test_db_session) -> None:
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, status) "
            "VALUES (1, 'PK-FOG', 'Package', 1) ON CONFLICT (package_id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, reference_id, package_name, "
            "diagnostic_provider, status, bookings_count) "
            "VALUES (1, 'REF-FOG', 'Diag', 'healthians', 1, 0) "
            "ON CONFLICT (diagnostic_package_id) DO NOTHING"
        )
    )


async def _seed_engagement(test_db_session, *, engagement_id: int) -> None:
    await _seed_diagnostic_package(test_db_session)
    existing = await test_db_session.get(Engagement, engagement_id)
    if existing is None:
        test_db_session.add(
            Engagement(
                engagement_id=engagement_id,
                engagement_name="Family Gift Test",
                engagement_code=f"FG{engagement_id}",
                engagement_type=None,
                assessment_package_id=1,
                diagnostic_package_id=1,
                city="BLR",
                slot_duration=20,
                start_date=date(2026, 10, 22),
                end_date=date(2026, 10, 22),
                status="running",
            )
        )
    await test_db_session.commit()


async def _seed_gift_services(test_db_session) -> None:
    for key, channel, path in (
        (SENDER_WHATSAPP_KEY, "whatsapp", "/family-onboard-sender-whatsapp-v1"),
        (SENDER_EMAIL_KEY, "email", "/family-onboard-sender-email-v1"),
        (RECEIVER_WHATSAPP_KEY, "whatsapp", "/family-onboard-receiver-whatsapp-v1"),
        (RECEIVER_EMAIL_KEY, "email", "/family-onboard-receiver-email-v1"),
    ):
        await test_db_session.execute(
            text(
                "INSERT INTO notification_services "
                "(service_key, display_name, channel, webhook_path, is_active, "
                "require_blood_report_url, require_bio_ai_report_url, require_participant_detail, "
                "require_otp, require_session_details, require_external_link) "
                "VALUES (:sk, :sk, :ch, :path, true, false, false, true, false, false, false) "
                "ON CONFLICT (service_key) DO UPDATE SET "
                "require_participant_detail = true, is_active = true, webhook_path = EXCLUDED.webhook_path"
            ),
            {"sk": key, "ch": channel, "path": path},
        )
    await test_db_session.commit()


def test_is_booker_plus_alias_email():
    assert _is_booker_plus_alias_email("adi+1234@example.com", "adi@example.com") is True
    assert _is_booker_plus_alias_email("adi@example.com", "adi@example.com") is False
    assert _is_booker_plus_alias_email("other@example.com", "adi@example.com") is False


async def _reload_user(test_db_session, user_id: int) -> User:
    row = await test_db_session.execute(select(User).where(User.user_id == user_id))
    return row.scalar_one()


@pytest.mark.asyncio
async def test_notify_family_onboard_gift_dispatches_four_services(test_db_session, monkeypatch):
    await _seed_gift_services(test_db_session)
    await _seed_engagement(test_db_session, engagement_id=88099)
    webhook_calls: list[dict] = []

    class _FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {"accepted": True}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json=None):
            webhook_calls.append({"url": url, "json": json})
            return _FakeResponse()

    monkeypatch.setattr("modules.notifications.service.httpx.AsyncClient", _FakeClient)

    booker = User(
        user_id=88001,
        first_name="Adi",
        last_name="Kumar",
        phone="9000880001",
        email="adi@example.com",
        is_participant=True,
        status="active",
    )
    recipient = User(
        user_id=88002,
        first_name="Akash",
        last_name="Kumar",
        phone="9000880002",
        email="akash.real@example.com",
        is_participant=True,
        status="active",
    )
    test_db_session.add_all([booker, recipient])
    await test_db_session.commit()
    booker = await _reload_user(test_db_session, 88001)
    recipient = await _reload_user(test_db_session, 88002)

    svc = NotificationsService(NotificationsRepository())
    await notify_family_onboard_gift(
        test_db_session,
        notifications_service=svc,
        booker=booker,
        recipient=recipient,
        engagement_id=88099,
        relationship="child",
    )

    assert len(webhook_calls) == 4
    rows = (
        await test_db_session.execute(
            text(
                "SELECT service_key FROM notifications WHERE engagement_id = :eid ORDER BY notification_id"
            ),
            {"eid": 88099},
        )
    ).scalars().all()
    assert set(rows) == set(_KEYS)


@pytest.mark.asyncio
async def test_notify_skips_receiver_email_for_plus_alias(test_db_session, monkeypatch):
    await _seed_gift_services(test_db_session)
    await _seed_engagement(test_db_session, engagement_id=88199)
    calls: list[str] = []

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"accepted": True}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json=None):
            if json and "notification_id" in json:
                calls.append(url)
            return _FakeResponse()

    monkeypatch.setattr("modules.notifications.service.httpx.AsyncClient", _FakeClient)

    booker = User(
        user_id=88101,
        first_name="Adi",
        last_name="K",
        phone="9000880101",
        email="adi@example.com",
        is_participant=True,
        status="active",
    )
    recipient = User(
        user_id=88102,
        first_name="Riya",
        last_name="K",
        phone="9000880102",
        email="adi+5678@example.com",
        is_participant=True,
        status="active",
    )
    test_db_session.add_all([booker, recipient])
    await test_db_session.commit()
    booker = await _reload_user(test_db_session, 88101)
    recipient = await _reload_user(test_db_session, 88102)

    svc = NotificationsService(NotificationsRepository())
    await notify_family_onboard_gift(
        test_db_session,
        notifications_service=svc,
        booker=booker,
        recipient=recipient,
        engagement_id=88199,
        relationship="spouse",
    )

    rows = (
        await test_db_session.execute(
            text("SELECT service_key FROM notifications WHERE engagement_id = :eid"),
            {"eid": 88199},
        )
    ).scalars().all()
    assert RECEIVER_EMAIL_KEY not in rows
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_notify_does_not_raise_when_dispatch_raises(test_db_session, monkeypatch):
    await _seed_gift_services(test_db_session)
    await _seed_engagement(test_db_session, engagement_id=88299)
    booker = User(
        user_id=88201,
        first_name="A",
        last_name="B",
        phone="9000880201",
        email="a@example.com",
        is_participant=True,
        status="active",
    )
    recipient = User(
        user_id=88202,
        first_name="C",
        last_name="D",
        phone="9000880202",
        email="c@example.com",
        is_participant=True,
        status="active",
    )
    test_db_session.add_all([booker, recipient])
    await test_db_session.commit()
    booker = await _reload_user(test_db_session, 88201)
    recipient = await _reload_user(test_db_session, 88202)

    svc = NotificationsService(NotificationsRepository())

    async def _raise_dispatch(*args, **kwargs):
        raise RuntimeError("dispatch failed")

    monkeypatch.setattr(svc, "dispatch", _raise_dispatch)
    await notify_family_onboard_gift(
        test_db_session,
        notifications_service=svc,
        booker=booker,
        recipient=recipient,
        engagement_id=88299,
        relationship="child",
    )


@pytest.mark.asyncio
async def test_notify_dedup_skips_second_send(test_db_session, monkeypatch):
    await _seed_gift_services(test_db_session)
    await _seed_engagement(test_db_session, engagement_id=88399)

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"accepted": True}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json=None):
            return _FakeResponse()

    monkeypatch.setattr("modules.notifications.service.httpx.AsyncClient", _FakeClient)

    booker = User(
        user_id=88301,
        first_name="Adi",
        last_name="K",
        phone="9000880301",
        email="adi2@example.com",
        is_participant=True,
        status="active",
    )
    recipient = User(
        user_id=88302,
        first_name="Akash",
        last_name="K",
        phone="9000880302",
        email="akash2@example.com",
        is_participant=True,
        status="active",
    )
    test_db_session.add_all([booker, recipient])
    await test_db_session.commit()
    booker = await _reload_user(test_db_session, 88301)
    recipient = await _reload_user(test_db_session, 88302)

    svc = NotificationsService(NotificationsRepository())
    await notify_family_onboard_gift(
        test_db_session,
        notifications_service=svc,
        booker=booker,
        recipient=recipient,
        engagement_id=88399,
        relationship="child",
    )
    first_count = (
        await test_db_session.execute(
            text("SELECT COUNT(*) FROM notifications WHERE engagement_id = :eid"),
            {"eid": 88399},
        )
    ).scalar_one()

    await notify_family_onboard_gift(
        test_db_session,
        notifications_service=svc,
        booker=booker,
        recipient=recipient,
        engagement_id=88399,
        relationship="child",
    )
    second_count = (
        await test_db_session.execute(
            text("SELECT COUNT(*) FROM notifications WHERE engagement_id = :eid"),
            {"eid": 88399},
        )
    ).scalar_one()
    assert first_count == 4
    assert second_count == first_count
