"""Tests for GET /notifications admin list (filters and enrichment)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from core.config import settings
from core.security import create_jwt_token
from modules.employee.models import Employee
from modules.notifications.models import Notification
from modules.users.models import User


def _auth_header(employee_id: int) -> dict[str, str]:
    from tests.helpers.auth import employee_auth_header
    return employee_auth_header(employee_id)


async def _seed_employee(test_db_session, *, user_id: int, employee_id: int):
    test_db_session.add(
        User(user_id=user_id, age=30, phone=f"{user_id}000000000", status="active", first_name="Admin")
    )
    await test_db_session.flush()
    test_db_session.add(
        Employee(employee_id=employee_id, name=f"Employee {employee_id}", phone=str(employee_id).zfill(10)[:15], email=f"employee{employee_id}@test.example", role="admin", status="active")
    )
    await test_db_session.commit()


async def _seed_service(test_db_session, *, service_key: str, display_name: str, channel: str = "whatsapp"):
    await test_db_session.execute(
        text(
            "INSERT INTO notification_services "
            "(service_key, display_name, channel, template_name, email_subject, email_body, is_active, require_blood_report_url, require_bio_ai_report_url, require_participant_detail) "
            "VALUES (:sk, :dn, :ch, 'test_tpl', 'Test', 'Test', true, false, false, false) "
            "ON CONFLICT (service_key) DO UPDATE SET display_name = EXCLUDED.display_name"
        ),
        {"sk": service_key, "dn": display_name, "ch": channel},
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_list_notifications_requires_employee(async_client, test_db_session):
    response = await async_client.get("/notifications")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_notifications_enriched_fields(async_client, test_db_session):
    await _seed_employee(test_db_session, user_id=9601, employee_id=9601)
    await _seed_service(
        test_db_session,
        service_key="welcome-whatsapp-test",
        display_name="Welcome WhatsApp",
    )

    test_db_session.add(
        User(
            user_id=9602,
            age=30,
            phone="9602000000",
            status="active",
            first_name="Alex",
            last_name="Test",
        )
    )
    from tests.modules.notifications.sql_helpers import engagement_status_code

    await test_db_session.execute(
        text(
            "INSERT INTO engagements "
            "(engagement_id, engagement_name, engagement_code, engagement_type, assessment_package_id, "
            "diagnostic_package_id, city, slot_duration, start_date, end_date, status) "
            "VALUES (9603, 'Summer Camp', 'ENG-LIST-9603', "
            "(SELECT id FROM engagement_types WHERE code = 'bio_ai'), 1, 1, 'BLR', 20, "
            f"'2026-05-01', '2026-05-01', {engagement_status_code('running')})"
        )
    )
    dispatched = datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc)
    test_db_session.add(
        Notification(
            service_key="welcome-whatsapp-test",
            status="sent",
            channel="whatsapp",
            user={"user_ids": [9602]},
            engagement_id=9603,
            message="ok",
            dispatched_at=dispatched,
            completed_at=dispatched,
        )
    )
    await test_db_session.commit()

    response = await async_client.get("/notifications?limit=5", headers=_auth_header(9601))
    assert response.status_code == 200
    body = response.json()
    row = next(
        (r for r in body["data"] if r.get("engagement_id") == 9603),
        None,
    )
    assert row is not None
    assert row["service_display_name"] == "Welcome WhatsApp"
    assert row["engagement_name"] == "Summer Camp"
    assert row["engagement_code"] == "ENG-LIST-9603"
    assert len(row["recipients"]) == 1
    assert row["recipients"][0]["user_id"] == 9602
    assert row["recipients"][0]["first_name"] == "Alex"


@pytest.mark.asyncio
async def test_list_notifications_filter_by_event_code(async_client, test_db_session):
    await _seed_employee(test_db_session, user_id=9606, employee_id=9606)
    await _seed_service(test_db_session, service_key="evt-filter-a", display_name="Event A")
    await _seed_service(test_db_session, service_key="evt-filter-b", display_name="Event B")

    test_db_session.add(
        Notification(
            event_code="reminders.pretest",
            service_key="evt-filter-a",
            status="sent",
            channel="email",
            user={"user_ids": [9606]},
            message="pretest",
            dispatched_at=datetime.now(timezone.utc),
        )
    )
    test_db_session.add(
        Notification(
            event_code="reports.blood_ready",
            service_key="evt-filter-b",
            status="sent",
            channel="email",
            user={"user_ids": [9606]},
            message="blood",
            dispatched_at=datetime.now(timezone.utc),
        )
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/notifications?event_code=reminders.pretest&limit=50",
        headers=_auth_header(9606),
    )
    assert response.status_code == 200
    rows = response.json()["data"]
    assert all(r.get("event_code") == "reminders.pretest" for r in rows)
    assert any(r.get("message") == "pretest" for r in rows)
    assert not any(r.get("message") == "blood" for r in rows)


@pytest.mark.asyncio
async def test_list_notifications_enriches_contact_recipients(async_client, test_db_session):
    await _seed_employee(test_db_session, user_id=9610, employee_id=9610)
    await _seed_service(
        test_db_session,
        service_key="booking-alert-contacts-test",
        display_name="Booking Alert Contacts",
    )

    from modules.partners.models import Partner

    test_db_session.add(
        Partner(
            partner_id=9611,
            name="Priya Assistant",
            phone="9611000000",
            email="priya@example.com",
            role="phlebo",
            status="active",
        )
    )
    test_db_session.add(
        Notification(
            service_key="booking-alert-contacts-test",
            status="sent",
            channel="whatsapp",
            user={"contacts": [{"phone": "9611000000", "email": "priya@example.com"}]},
            engagement_id=None,
            message="ok",
            dispatched_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
    )
    test_db_session.add(
        Notification(
            service_key="booking-alert-contacts-test",
            status="sent",
            channel="whatsapp",
            user={
                "contacts": [
                    {
                        "first_name": "Sunil",
                        "last_name": "OA",
                        "phone": "8424029541",
                        "email": "sunil@example.com",
                    }
                ]
            },
            engagement_id=None,
            message="named",
            dispatched_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/notifications?service_key=booking-alert-contacts-test&limit=50",
        headers=_auth_header(9610),
    )
    assert response.status_code == 200
    rows = response.json()["data"]
    by_message = {r["message"]: r for r in rows}

    legacy = by_message["ok"]
    assert len(legacy["recipients"]) == 1
    assert legacy["recipients"][0]["user_id"] is None
    assert legacy["recipients"][0]["first_name"] == "Priya"
    assert legacy["recipients"][0]["last_name"] == "Assistant"

    named = by_message["named"]
    assert len(named["recipients"]) == 1
    assert named["recipients"][0]["first_name"] == "Sunil"
    assert named["recipients"][0]["last_name"] == "OA"


@pytest.mark.asyncio
async def test_list_notifications_multi_status_filter(async_client, test_db_session):
    await _seed_employee(test_db_session, user_id=9604, employee_id=9604)
    await _seed_service(test_db_session, service_key="multi-status-svc", display_name="Multi")

    for st in ("pending", "sent", "failed"):
        test_db_session.add(
            Notification(
                service_key="multi-status-svc",
                status=st,
                channel="email",
                user={"user_ids": [9604]},
                message=st,
                dispatched_at=datetime.now(timezone.utc),
            )
        )
    await test_db_session.commit()

    response = await async_client.get(
        "/notifications?status=pending,failed&service_key=multi-status-svc&limit=50",
        headers=_auth_header(9604),
    )
    assert response.status_code == 200
    statuses = {r["status"] for r in response.json()["data"]}
    assert statuses <= {"pending", "failed"}
    assert "sent" not in statuses
    assert len(statuses) >= 1


@pytest.mark.asyncio
async def test_list_notifications_dispatched_at_range(async_client, test_db_session):
    await _seed_employee(test_db_session, user_id=9605, employee_id=9605)
    await _seed_service(test_db_session, service_key="date-filter-svc", display_name="Date")

    old = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    recent = datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc)
    test_db_session.add(
        Notification(
            service_key="date-filter-svc",
            status="sent",
            channel="whatsapp",
            user={"user_ids": [9605]},
            message="old",
            dispatched_at=old,
        )
    )
    test_db_session.add(
        Notification(
            service_key="date-filter-svc",
            status="sent",
            channel="whatsapp",
            user={"user_ids": [9605]},
            message="recent",
            dispatched_at=recent,
        )
    )
    await test_db_session.commit()

    from_iso = "2026-05-01T00:00:00Z"
    to_iso = "2026-05-31T23:59:59Z"
    response = await async_client.get(
        f"/notifications?service_key=date-filter-svc&dispatched_from={from_iso}&dispatched_to={to_iso}&limit=50",
        headers=_auth_header(9605),
    )
    assert response.status_code == 200
    messages = {r["message"] for r in response.json()["data"]}
    assert "recent" in messages
    assert "old" not in messages


@pytest.mark.asyncio
async def test_list_notifications_channel_filter(async_client, test_db_session):
    await _seed_employee(test_db_session, user_id=9606, employee_id=9606)
    await _seed_service(
        test_db_session, service_key="email-svc-list", display_name="Email", channel="email"
    )
    await _seed_service(
        test_db_session, service_key="wa-svc-list", display_name="WA", channel="whatsapp"
    )

    test_db_session.add(
        Notification(
            service_key="email-svc-list",
            status="sent",
            channel="email",
            user={"user_ids": [9606]},
            dispatched_at=datetime.now(timezone.utc),
        )
    )
    test_db_session.add(
        Notification(
            service_key="wa-svc-list",
            status="sent",
            channel="whatsapp",
            user={"user_ids": [9606]},
            dispatched_at=datetime.now(timezone.utc),
        )
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/notifications?channel=email&limit=50",
        headers=_auth_header(9606),
    )
    assert response.status_code == 200
    for row in response.json()["data"]:
        if row["service_key"] in ("email-svc-list", "wa-svc-list"):
            assert row["channel"] == "email"


@pytest.mark.asyncio
async def test_list_notifications_search_by_message_and_recipient(async_client, test_db_session):
    await _seed_employee(test_db_session, user_id=9620, employee_id=9620)
    await _seed_service(test_db_session, service_key="search-msg-svc", display_name="Search Msg")
    await _seed_service(test_db_session, service_key="search-user-svc", display_name="Search User")

    test_db_session.add(
        User(
            user_id=9621,
            age=28,
            phone="9621000000",
            status="active",
            first_name="Riya",
            last_name="Kapoor",
        )
    )
    test_db_session.add(
        User(
            user_id=9622,
            age=31,
            phone="9622000000",
            status="active",
            first_name="Other",
            last_name="Person",
        )
    )
    test_db_session.add(
        Notification(
            service_key="search-msg-svc",
            status="sent",
            channel="whatsapp",
            user={"user_ids": [9622]},
            message="OTP sent successfully UNIQUE-MSG-TOKEN",
            dispatched_at=datetime.now(timezone.utc),
        )
    )
    test_db_session.add(
        Notification(
            service_key="search-user-svc",
            status="failed",
            channel="email",
            user={"user_ids": [9621]},
            message="delivery failed",
            dispatched_at=datetime.now(timezone.utc),
        )
    )
    test_db_session.add(
        Notification(
            service_key="search-user-svc",
            status="sent",
            channel="whatsapp",
            user={"user_ids": [9622]},
            message="unrelated row",
            dispatched_at=datetime.now(timezone.utc),
        )
    )
    await test_db_session.commit()

    by_message = await async_client.get(
        "/notifications?search=UNIQUE-MSG-TOKEN&limit=50",
        headers=_auth_header(9620),
    )
    assert by_message.status_code == 200
    message_rows = by_message.json()["data"]
    assert any(r.get("message") == "OTP sent successfully UNIQUE-MSG-TOKEN" for r in message_rows)
    assert all("UNIQUE-MSG-TOKEN" in (r.get("message") or "") for r in message_rows)

    by_name = await async_client.get(
        "/notifications?search=Riya&service_key=search-user-svc&limit=50",
        headers=_auth_header(9620),
    )
    assert by_name.status_code == 200
    name_rows = by_name.json()["data"]
    assert len(name_rows) >= 1
    assert all(r.get("service_key") == "search-user-svc" for r in name_rows)
    assert any(
        any((rec.get("first_name") or "") == "Riya" for rec in (r.get("recipients") or []))
        for r in name_rows
    )

    by_phone = await async_client.get(
        "/notifications?search=9621000000&service_key=search-user-svc&limit=50",
        headers=_auth_header(9620),
    )
    assert by_phone.status_code == 200
    phone_rows = by_phone.json()["data"]
    assert len(phone_rows) >= 1
    assert any(
        any((rec.get("first_name") or "") == "Riya" for rec in (r.get("recipients") or []))
        for r in phone_rows
    )
