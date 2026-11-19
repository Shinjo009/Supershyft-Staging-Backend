"""Tests for notification deduplication helpers used by cron jobs."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import text

from modules.notifications.dedup import (
    has_notification_been_sent,
    should_skip_contact_notification,
    should_skip_notification,
    should_skip_notification_on_date,
)
from modules.notifications.models import Notification
from modules.users.models import User

_TEST_EVENT = "test.dedup.event"
_TEST_EVENT_B = "test.dedup.event_b"


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


async def _seed_engagement(test_db_session, *, engagement_id: int) -> None:
    from tests.modules.notifications.sql_helpers import engagement_status_code

    await test_db_session.execute(
        text(
            "INSERT INTO engagements "
            "(engagement_id, engagement_name, engagement_code, engagement_type, assessment_package_id, "
            "diagnostic_package_id, city, slot_duration, start_date, end_date, status) "
            f"VALUES ({engagement_id}, 'Camp', 'ENG-DEDUP-{engagement_id}', "
            "(SELECT id FROM engagement_types WHERE code = 'bio_ai'), 1, 1, 'BLR', 20, "
            f"'2026-05-01', '2026-05-01', {engagement_status_code('running')})"
        )
    )
    await test_db_session.commit()


async def _seed_notification(
    test_db_session,
    *,
    service_key: str,
    user_id: int,
    engagement_id: int,
    status: str,
    dispatched_at: datetime | None = None,
    event_code: str | None = _TEST_EVENT,
) -> None:
    test_db_session.add(
        Notification(
            event_code=event_code,
            service_key=service_key,
            status=status,
            channel="email",
            user={"user_ids": [user_id]},
            engagement_id=engagement_id,
            message="test",
            dispatched_at=dispatched_at,
        )
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_should_skip_when_no_prior_notification(test_db_session):
    await _seed_service(test_db_session, service_key="dedup-svc-a")
    await _seed_engagement(test_db_session, engagement_id=9701)

    result = await should_skip_notification(
        test_db_session,
        event_code=_TEST_EVENT,
        user_id=42,
        engagement_id=9701,
    )
    assert result is None
    assert not await has_notification_been_sent(
        test_db_session,
        event_code=_TEST_EVENT,
        user_id=42,
        engagement_id=9701,
    )


@pytest.mark.asyncio
async def test_should_skip_when_prior_sent(test_db_session):
    await _seed_service(test_db_session, service_key="dedup-svc-b")
    await _seed_engagement(test_db_session, engagement_id=9702)
    await _seed_notification(
        test_db_session,
        service_key="dedup-svc-b",
        user_id=42,
        engagement_id=9702,
        status="sent",
    )

    result = await should_skip_notification(
        test_db_session,
        event_code=_TEST_EVENT,
        user_id=42,
        engagement_id=9702,
    )
    assert result == "already sent"
    assert await has_notification_been_sent(
        test_db_session,
        event_code=_TEST_EVENT,
        user_id=42,
        engagement_id=9702,
    )


@pytest.mark.asyncio
async def test_legacy_service_key_sent_skips_when_event_matches_backfill(test_db_session):
    await _seed_service(test_db_session, service_key="dedup-svc-legacy")
    await _seed_engagement(test_db_session, engagement_id=97021)
    await _seed_notification(
        test_db_session,
        service_key="dedup-svc-legacy",
        user_id=42,
        engagement_id=97021,
        status="sent",
        event_code=None,
    )

    result = await should_skip_notification(
        test_db_session,
        event_code=_TEST_EVENT,
        user_id=42,
        engagement_id=97021,
        service_key="dedup-svc-legacy",
    )
    assert result == "already sent"


@pytest.mark.asyncio
async def test_should_not_skip_when_prior_failed(test_db_session):
    await _seed_service(test_db_session, service_key="dedup-svc-c")
    await _seed_engagement(test_db_session, engagement_id=9703)
    await _seed_notification(
        test_db_session,
        service_key="dedup-svc-c",
        user_id=42,
        engagement_id=9703,
        status="failed",
    )

    result = await should_skip_notification(
        test_db_session,
        event_code=_TEST_EVENT,
        user_id=42,
        engagement_id=9703,
    )
    assert result is None


@pytest.mark.asyncio
async def test_should_skip_when_prior_pending_in_flight(test_db_session):
    await _seed_service(test_db_session, service_key="dedup-svc-d")
    await _seed_engagement(test_db_session, engagement_id=9704)
    await _seed_notification(
        test_db_session,
        service_key="dedup-svc-d",
        user_id=42,
        engagement_id=9704,
        status="pending",
        dispatched_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )

    result = await should_skip_notification(
        test_db_session,
        event_code=_TEST_EVENT,
        user_id=42,
        engagement_id=9704,
        pending_timeout_hours=2,
    )
    assert result == "already in flight"


@pytest.mark.asyncio
async def test_should_not_skip_when_prior_pending_is_stale(test_db_session):
    await _seed_service(test_db_session, service_key="dedup-svc-d2")
    await _seed_engagement(test_db_session, engagement_id=97041)
    await _seed_notification(
        test_db_session,
        service_key="dedup-svc-d2",
        user_id=42,
        engagement_id=97041,
        status="pending",
        dispatched_at=datetime.now(timezone.utc) - timedelta(hours=5),
    )

    result = await should_skip_notification(
        test_db_session,
        event_code=_TEST_EVENT,
        user_id=42,
        engagement_id=97041,
        pending_timeout_hours=2,
    )
    assert result is None


@pytest.mark.asyncio
async def test_should_not_skip_for_different_user(test_db_session):
    await _seed_service(test_db_session, service_key="dedup-svc-e")
    await _seed_engagement(test_db_session, engagement_id=9705)
    test_db_session.add(User(user_id=99, age=30, phone="9900000000", status="active"))
    await _seed_notification(
        test_db_session,
        service_key="dedup-svc-e",
        user_id=99,
        engagement_id=9705,
        status="sent",
    )

    result = await should_skip_notification(
        test_db_session,
        event_code=_TEST_EVENT,
        user_id=42,
        engagement_id=9705,
    )
    assert result is None


@pytest.mark.asyncio
async def test_same_event_cross_channel_dedup(test_db_session):
    await _seed_service(test_db_session, service_key="dedup-svc-email")
    await _seed_service(test_db_session, service_key="dedup-svc-whatsapp")
    await _seed_engagement(test_db_session, engagement_id=9706)
    await _seed_notification(
        test_db_session,
        service_key="dedup-svc-email",
        user_id=42,
        engagement_id=9706,
        status="sent",
    )

    skip = await should_skip_notification(
        test_db_session,
        event_code=_TEST_EVENT,
        user_id=42,
        engagement_id=9706,
        service_key="dedup-svc-whatsapp",
    )
    assert skip == "already sent"


@pytest.mark.asyncio
async def test_different_events_remain_independent(test_db_session):
    await _seed_service(test_db_session, service_key="dedup-svc-x")
    await _seed_engagement(test_db_session, engagement_id=97062)
    await _seed_notification(
        test_db_session,
        service_key="dedup-svc-x",
        user_id=42,
        engagement_id=97062,
        status="sent",
        event_code=_TEST_EVENT,
    )

    skip = await should_skip_notification(
        test_db_session,
        event_code=_TEST_EVENT_B,
        user_id=42,
        engagement_id=97062,
    )
    assert skip is None


@pytest.mark.asyncio
async def test_service_rebind_same_event_skips(test_db_session):
    await _seed_service(test_db_session, service_key="dedup-svc-old")
    await _seed_service(test_db_session, service_key="dedup-svc-new")
    await _seed_engagement(test_db_session, engagement_id=97063)
    await _seed_notification(
        test_db_session,
        service_key="dedup-svc-old",
        user_id=42,
        engagement_id=97063,
        status="sent",
        event_code=_TEST_EVENT,
    )

    skip = await should_skip_notification(
        test_db_session,
        event_code=_TEST_EVENT,
        user_id=42,
        engagement_id=97063,
        service_key="dedup-svc-new",
    )
    assert skip == "already sent"


@pytest.mark.asyncio
async def test_contact_dedup_same_event(test_db_session):
    await _seed_service(test_db_session, service_key="dedup-contact")
    await _seed_engagement(test_db_session, engagement_id=9707)
    test_db_session.add(
        Notification(
            event_code=_TEST_EVENT,
            service_key="dedup-contact",
            status="sent",
            channel="whatsapp",
            user={"contacts": [{"phone": "9000000001", "partner_id": 1}]},
            engagement_id=9707,
            message="sent",
        )
    )
    await test_db_session.commit()

    skip = await should_skip_contact_notification(
        test_db_session,
        event_code=_TEST_EVENT,
        engagement_id=9707,
        partner_id=1,
        phone="9000000001",
        service_key="dedup-contact-other",
    )
    assert skip == "already sent"


@pytest.mark.asyncio
async def test_should_skip_notification_on_date_allows_resend_on_next_day(test_db_session):
    await _seed_service(test_db_session, service_key="dedup-on-date-a")
    await _seed_engagement(test_db_session, engagement_id=97071)
    yesterday = date(2026, 6, 9)
    today = date(2026, 6, 10)
    await _seed_notification(
        test_db_session,
        service_key="dedup-on-date-a",
        user_id=42,
        engagement_id=97071,
        status="sent",
        dispatched_at=datetime.combine(yesterday, time(12, 0), tzinfo=timezone.utc),
    )

    yesterday_skip = await should_skip_notification_on_date(
        test_db_session,
        event_code=_TEST_EVENT,
        user_id=42,
        engagement_id=97071,
        reference_date=yesterday,
    )
    today_skip = await should_skip_notification_on_date(
        test_db_session,
        event_code=_TEST_EVENT,
        user_id=42,
        engagement_id=97071,
        reference_date=today,
    )

    assert yesterday_skip == "already sent"
    assert today_skip is None


@pytest.mark.asyncio
async def test_should_skip_notification_on_date_blocks_same_day_resend(test_db_session):
    await _seed_service(test_db_session, service_key="dedup-on-date-b")
    await _seed_engagement(test_db_session, engagement_id=9708)
    reference_date = date(2026, 6, 10)
    await _seed_notification(
        test_db_session,
        service_key="dedup-on-date-b",
        user_id=42,
        engagement_id=9708,
        status="sent",
        dispatched_at=datetime.combine(reference_date, time(6, 30), tzinfo=timezone.utc),
    )

    result = await should_skip_notification_on_date(
        test_db_session,
        event_code=_TEST_EVENT,
        user_id=42,
        engagement_id=9708,
        reference_date=reference_date,
    )

    assert result == "already sent"