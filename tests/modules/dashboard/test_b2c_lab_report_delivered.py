"""B2C lab_report_delivered KPI: summary count + detail list."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from modules.engagements.models import Engagement, EngagementParticipant
from modules.notifications.models import Notification
from modules.organizations.models import Organization
from modules.users.models import User
from tests.helpers.auth import employee_auth_header, seed_employee


async def _ensure_notification_service(test_db_session, *, service_key: str, channel: str) -> None:
    await test_db_session.execute(
        text(
            "INSERT INTO notification_services "
            "(service_key, display_name, channel, template_name, email_subject, email_body, "
            "is_active, require_blood_report_url, require_bio_ai_report_url, require_participant_detail) "
            "VALUES (:sk, :sk, :channel, 'test-hook', 'Test', 'Test', true, false, false, false) "
            "ON CONFLICT (service_key) DO NOTHING"
        ),
        {"sk": service_key, "channel": channel},
    )


async def _seed_b2c_user_engagement(
    test_db_session,
    *,
    user_id: int,
    engagement_id: int,
    engagement_participant_id: int,
    organization_id: int | None,
    created_at: datetime | None = None,
) -> None:
    today = date.today()
    test_db_session.add(
        User(
            user_id=user_id,
            first_name=f"User{user_id}",
            last_name="Lab",
            phone=f"{user_id:010d}",
            email=f"user{user_id}@example.com",
            age=30,
            status="active",
            created_at=created_at or datetime.now(timezone.utc),
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        Engagement(
            engagement_id=engagement_id,
            engagement_code=f"LAB-{engagement_id}",
            engagement_name=f"Lab Eng {engagement_id}",
            organization_id=organization_id,
            city="Bengaluru",
            start_date=today,
            end_date=today,
            status="running",
            slot_duration=20,
            diagnostic_package_id=1,
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        EngagementParticipant(
            engagement_participant_id=engagement_participant_id,
            engagement_id=engagement_id,
            user_id=user_id,
        )
    )


@pytest.mark.asyncio
async def test_b2c_lab_report_delivered_summary_and_list(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8840, role="admin")
    await _ensure_notification_service(
        test_db_session, service_key="b2c-blood-email", channel="email"
    )
    await _ensure_notification_service(
        test_db_session, service_key="b2c-blood-wa", channel="whatsapp"
    )

    now = datetime.now(timezone.utc)
    old = now - timedelta(days=40)

    # B2C user with sent blood report (in period)
    await _seed_b2c_user_engagement(
        test_db_session,
        user_id=88401,
        engagement_id=88401,
        engagement_participant_id=8840101,
        organization_id=None,
    )
    # B2C user with failed notification — excluded
    await _seed_b2c_user_engagement(
        test_db_session,
        user_id=88402,
        engagement_id=88402,
        engagement_participant_id=8840201,
        organization_id=None,
    )
    test_db_session.add(
        Organization(
            organization_id=88400,
            name="B2B Org Lab",
            organization_type="corporate",
            status="active",
        )
    )
    await test_db_session.flush()

    # B2B user with sent blood report — excluded from B2C
    await _seed_b2c_user_engagement(
        test_db_session,
        user_id=88403,
        engagement_id=88403,
        engagement_participant_id=8840301,
        organization_id=88400,
    )
    # B2C user with sent blood report outside this_week — still in all_time
    await _seed_b2c_user_engagement(
        test_db_session,
        user_id=88404,
        engagement_id=88404,
        engagement_participant_id=8840401,
        organization_id=None,
    )

    test_db_session.add_all(
        [
            Notification(
                event_code="reports.blood_ready",
                service_key="b2c-blood-email",
                status="sent",
                channel="email",
                user={"user_ids": [88401]},
                engagement_id=88401,
                message="b2c blood sent",
                dispatched_at=now,
            ),
            Notification(
                event_code="reports.blood_ready",
                service_key="b2c-blood-wa",
                status="sent",
                channel="whatsapp",
                user={"user_ids": [88401]},
                engagement_id=88401,
                message="b2c blood wa",
                dispatched_at=now,
            ),
            Notification(
                event_code="reports.blood_ready",
                service_key="b2c-blood-email",
                status="failed",
                channel="email",
                user={"user_ids": [88402]},
                engagement_id=88402,
                message="failed",
                dispatched_at=now,
            ),
            Notification(
                event_code="reports.blood_ready",
                service_key="b2c-blood-email",
                status="sent",
                channel="email",
                user={"user_ids": [88403]},
                engagement_id=88403,
                message="b2b sent",
                dispatched_at=now,
            ),
            Notification(
                event_code="reports.blood_ready",
                service_key="b2c-blood-email",
                status="sent",
                channel="email",
                user={"user_ids": [88404]},
                engagement_id=88404,
                message="old sent",
                dispatched_at=old,
            ),
        ]
    )
    await test_db_session.commit()

    headers = employee_auth_header(8840)

    summary = await async_client.get(
        "/admin/dashboard/command/b2c/summary",
        params={"period": "all_time"},
        headers=headers,
    )
    assert summary.status_code == 200
    assert summary.json()["data"]["lab_report_delivered"] == 2

    this_week = await async_client.get(
        "/admin/dashboard/command/b2c/lab-report-delivered",
        params={"period": "this_week", "include_rows": "false"},
        headers=headers,
    )
    assert this_week.status_code == 200
    assert this_week.json()["meta"]["total"] == 1

    all_time = await async_client.get(
        "/admin/dashboard/command/b2c/lab-report-delivered",
        params={"period": "all_time", "include_rows": "true"},
        headers=headers,
    )
    assert all_time.status_code == 200
    body = all_time.json()
    assert body["meta"]["total"] == 2
    user_ids = {row["user_id"] for row in body["data"]}
    assert user_ids == {88401, 88404}
    row = next(r for r in body["data"] if r["user_id"] == 88401)
    assert row["lab_report"] == "sent"
    assert row["person"]["name"]
    assert "package" in row
    assert "collection" in row
    assert "blood_collection" in row
    assert "questionnaire" in row
    assert "lab_partner" in row
    assert "bio_ai" in row
    assert "consult" in row


@pytest.mark.asyncio
async def test_lab_report_sent_survives_newer_engagement(async_client, test_db_session):
    """Sent on an older engagement must still show lab_report=sent after a newer enroll."""
    await seed_employee(test_db_session, employee_id=8850, role="admin")
    await _ensure_notification_service(
        test_db_session, service_key="b2c-blood-email-multi", channel="email"
    )

    now = datetime.now(timezone.utc)
    today = date.today()
    older = today - timedelta(days=20)

    await _seed_b2c_user_engagement(
        test_db_session,
        user_id=88501,
        engagement_id=88501,
        engagement_participant_id=8850101,
        organization_id=None,
    )
    # Older engagement that actually received the blood-ready send
    eng_old = await test_db_session.get(Engagement, 88501)
    assert eng_old is not None
    eng_old.start_date = older
    eng_old.end_date = older

    # Newer engagement becomes "latest" for row building
    test_db_session.add(
        Engagement(
            engagement_id=88502,
            engagement_code="LAB-88502",
            engagement_name="Lab Eng 88502 newer",
            organization_id=None,
            city="Bengaluru",
            start_date=today,
            end_date=today,
            status="running",
            slot_duration=20,
            diagnostic_package_id=1,
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        EngagementParticipant(
            engagement_participant_id=8850201,
            engagement_id=88502,
            user_id=88501,
        )
    )
    test_db_session.add(
        Notification(
            event_code="reports.blood_ready",
            service_key="b2c-blood-email-multi",
            status="sent",
            channel="email",
            user={"user_ids": [88501]},
            engagement_id=88501,
            message="sent on older eng",
            dispatched_at=now,
        )
    )
    await test_db_session.commit()

    headers = employee_auth_header(8850)
    resp = await async_client.get(
        "/admin/dashboard/command/b2c/lab-report-delivered",
        params={"period": "all_time", "include_rows": "true"},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    row = next(r for r in body["data"] if r["user_id"] == 88501)
    assert row["lab_report"] == "sent"
