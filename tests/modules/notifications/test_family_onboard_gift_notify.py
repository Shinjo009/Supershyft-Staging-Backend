"""Unit tests for family-onboard Diwali gift notifications."""

from __future__ import annotations

from datetime import date
import pytest
from sqlalchemy import select, text

from core.exceptions import AppError
from db.column_types import STATUS_INTEGRATION_SYNC
from modules.bioai_report.client import BioAiReportsClient
from modules.engagements.models import Engagement
from modules.notifications.family_onboard_gift_notify import (
    GIFT_URL,
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

from tests.modules.notifications.dispatch_mocks import patch_service_direct_deliver

_KEYS = (
    SENDER_WHATSAPP_KEY,
    SENDER_EMAIL_KEY,
    RECEIVER_WHATSAPP_KEY,
    RECEIVER_EMAIL_KEY,
)

_TEST_CARD_URL = "https://bio-ai-reports.supershyft.com/r/test-family-gift-card"


@pytest.fixture(autouse=True)
def _stub_gift_cards_api(monkeypatch):
    async def _create_gift_card(self, payload):
        return {"url": _TEST_CARD_URL, "payload_echo": payload}

    monkeypatch.setattr(BioAiReportsClient, "create_gift_card", _create_gift_card)


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
    for key, channel, template in (
        (SENDER_WHATSAPP_KEY, "whatsapp", "family_onboard_sender_wa"),
        (SENDER_EMAIL_KEY, "email", "family_onboard_sender_email"),
        (RECEIVER_WHATSAPP_KEY, "whatsapp", "family_onboard_receiver_wa"),
        (RECEIVER_EMAIL_KEY, "email", "family_onboard_receiver_email"),
    ):
        if channel == "email":
            await test_db_session.execute(
                text(
                    "INSERT INTO notification_services "
                    "(service_key, display_name, channel, email_subject, email_body, is_active, "
                    "require_blood_report_url, require_bio_ai_report_url, require_participant_detail, "
                    "require_otp, require_session_details, require_external_link) "
                    "VALUES (:sk, :sk, :ch, 'Gift', 'Hello', true, false, false, true, false, false, false) "
                    "ON CONFLICT (service_key) DO UPDATE SET "
                    "require_participant_detail = true, is_active = true, email_subject = EXCLUDED.email_subject"
                ),
                {"sk": key, "ch": channel},
            )
        else:
            await test_db_session.execute(
                text(
                    "INSERT INTO notification_services "
                    "(service_key, display_name, channel, template_name, is_active, "
                    "require_blood_report_url, require_bio_ai_report_url, require_participant_detail, "
                    "require_otp, require_session_details, require_external_link) "
                    "VALUES (:sk, :sk, :ch, :tpl, true, false, false, true, false, false, false) "
                    "ON CONFLICT (service_key) DO UPDATE SET "
                    "require_participant_detail = true, is_active = true, template_name = EXCLUDED.template_name"
                ),
                {"sk": key, "ch": channel, "tpl": template},
            )
    await test_db_session.commit()


def _call_service_key(call: dict) -> str:
    svc = call.get("svc")
    return str(getattr(svc, "service_key", "") or "")


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
    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)

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

    assert len(deliver_calls) == 4
    rows = (
        await test_db_session.execute(
            text(
                "SELECT service_key FROM notifications WHERE engagement_id = :eid ORDER BY notification_id"
            ),
            {"eid": 88099},
        )
    ).scalars().all()
    assert set(rows) == set(_KEYS)

    receiver_calls = [
        c for c in deliver_calls if RECEIVER_WHATSAPP_KEY == _call_service_key(c)
    ]
    sender_calls = [
        c for c in deliver_calls if SENDER_WHATSAPP_KEY == _call_service_key(c)
    ]
    assert len(receiver_calls) == 1
    assert len(sender_calls) == 1
    assert receiver_calls[0]["participant_details"]["gift_url"] == _TEST_CARD_URL
    assert sender_calls[0]["participant_details"]["gift_url"] == GIFT_URL
    assert sender_calls[0]["participant_details"]["booker_phone"] == booker.phone

    sync_row = (
        await test_db_session.execute(
            text(
                "SELECT status, api_endpoint_url, response_payload "
                "FROM integration_sync_logs "
                "WHERE provider = 'bio_ai_reports' AND engagement_id = :eid AND user_id = :uid"
            ),
            {"eid": 88099, "uid": 88002},
        )
    ).first()
    assert sync_row is not None
    assert sync_row.status == STATUS_INTEGRATION_SYNC["success"]
    assert str(sync_row.api_endpoint_url).endswith("/api/cards")
    assert (sync_row.response_payload or {}).get("url") == _TEST_CARD_URL


@pytest.mark.asyncio
async def test_receiver_gift_card_api_failure_falls_back_to_app_url(test_db_session, monkeypatch):
    await _seed_gift_services(test_db_session)
    await _seed_engagement(test_db_session, engagement_id=88089)
    deliver_calls: list[dict] = []

    async def _fail_create(self, payload):
        raise AppError(
            status_code=502,
            error_code="BIO_AI_REPORTS_ERROR",
            message="bio-ai-reports request failed",
        )

    monkeypatch.setattr(BioAiReportsClient, "create_gift_card", _fail_create)
    patch_service_direct_deliver(monkeypatch, deliver_calls)

    booker = User(
        user_id=88081,
        first_name="Aanya",
        last_name="K",
        phone="9000880081",
        email="aanya@example.com",
        is_participant=True,
        status="active",
    )
    recipient = User(
        user_id=88082,
        first_name="Rohan",
        last_name="K",
        phone="9000880082",
        email="rohan@example.com",
        is_participant=True,
        status="active",
    )
    test_db_session.add_all([booker, recipient])
    await test_db_session.commit()
    booker = await _reload_user(test_db_session, 88081)
    recipient = await _reload_user(test_db_session, 88082)

    svc = NotificationsService(NotificationsRepository())
    await notify_family_onboard_gift(
        test_db_session,
        notifications_service=svc,
        booker=booker,
        recipient=recipient,
        engagement_id=88089,
        relationship="sister",
        booker_message="Wishing you joy and light.",
    )

    receiver_calls = [
        c for c in deliver_calls if RECEIVER_WHATSAPP_KEY == _call_service_key(c)
    ]
    assert len(receiver_calls) == 1
    assert receiver_calls[0]["participant_details"]["gift_url"] == GIFT_URL

    failed_row = (
        await test_db_session.execute(
            text(
                "SELECT status, api_endpoint_url "
                "FROM integration_sync_logs "
                "WHERE provider = 'bio_ai_reports' AND engagement_id = :eid AND user_id = :uid"
            ),
            {"eid": 88089, "uid": 88082},
        )
    ).first()
    assert failed_row is not None
    assert failed_row.status == STATUS_INTEGRATION_SYNC["failed"]
    assert str(failed_row.api_endpoint_url).endswith("/api/cards")


@pytest.mark.asyncio
async def test_notify_skips_receiver_email_for_plus_alias(test_db_session, monkeypatch):
    await _seed_gift_services(test_db_session)
    await _seed_engagement(test_db_session, engagement_id=88199)
    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)

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
    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)

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
