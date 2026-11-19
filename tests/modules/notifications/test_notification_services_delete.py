"""Tests for notification service delete gating and can_delete on list."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from modules.notifications.models import Notification
from modules.users.models import User
from modules.employee.models import Employee


def _auth_header(employee_id: int) -> dict[str, str]:
    from tests.helpers.auth import employee_auth_header

    return employee_auth_header(employee_id)


async def _seed_employee(test_db_session, *, user_id: int, employee_id: int):
    test_db_session.add(
        User(
            user_id=user_id,
            age=30,
            phone=f"{user_id}000000000",
            status="active",
            first_name="Admin",
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        Employee(
            employee_id=employee_id,
            name=f"Employee {employee_id}",
            phone=str(employee_id).zfill(10)[:15],
            email=f"employee{employee_id}@test.example",
            role="admin",
            status="active",
        )
    )
    await test_db_session.commit()


async def _seed_service(
    test_db_session,
    *,
    service_key: str,
    display_name: str,
    channel: str = "whatsapp",
) -> int:
    await test_db_session.execute(
        text(
            """
            INSERT INTO notification_services (
                service_key, display_name, channel, template_name,
                email_subject, email_body, is_active,
                require_blood_report_url, require_bio_ai_report_url, require_participant_detail
            )
            VALUES (
                :sk, :dn, :ch, 'test_tpl', 'Test', 'Test', true, false, false, false
            )
            ON CONFLICT (service_key) DO UPDATE SET display_name = EXCLUDED.display_name
            """
        ),
        {"sk": service_key, "dn": display_name, "ch": channel},
    )
    await test_db_session.commit()
    row = await test_db_session.execute(
        text(
            "SELECT notification_service_id FROM notification_services WHERE service_key = :sk"
        ),
        {"sk": service_key},
    )
    return int(row.scalar_one())


def _find_service(payload: list[dict], service_key: str) -> dict:
    for item in payload:
        if item.get("service_key") == service_key:
            return item
    raise AssertionError(f"service {service_key} not in list response")


@pytest.mark.asyncio
async def test_list_marks_unused_service_can_delete(async_client, test_db_session):
    await _seed_employee(test_db_session, user_id=98101, employee_id=98101)
    await _seed_service(
        test_db_session, service_key="svc-del-free", display_name="Unused Svc"
    )

    response = await async_client.get(
        "/notifications/services",
        headers=_auth_header(98101),
    )
    assert response.status_code == 200
    item = _find_service(response.json()["data"], "svc-del-free")
    assert item["can_delete"] is True


@pytest.mark.asyncio
async def test_delete_unused_service_succeeds(async_client, test_db_session):
    await _seed_employee(test_db_session, user_id=98102, employee_id=98102)
    sid = await _seed_service(
        test_db_session, service_key="svc-del-ok", display_name="Delete Me"
    )

    response = await async_client.delete(
        f"/notifications/services/{sid}",
        headers=_auth_header(98102),
    )
    assert response.status_code == 200
    assert response.json()["data"]["deleted"] is True


@pytest.mark.asyncio
async def test_list_and_delete_blocked_by_notification_event(async_client, test_db_session):
    await _seed_employee(test_db_session, user_id=98103, employee_id=98103)
    sid = await _seed_service(
        test_db_session, service_key="svc-bound-event", display_name="Bound Event"
    )
    await test_db_session.execute(
        text(
            """
            INSERT INTO notification_events (
                event_code, event_name, recipient_type, delivery_channel,
                notification_services, condition_key
            )
            VALUES (
                'test.delete_gate', 'Delete gate', 'user', 'whatsapp',
                CAST(:services AS jsonb), 'default'
            )
            ON CONFLICT DO NOTHING
            """
        ),
        {"services": json.dumps([{"service_key": "svc-bound-event"}])},
    )
    await test_db_session.commit()

    list_resp = await async_client.get(
        "/notifications/services",
        headers=_auth_header(98103),
    )
    item = _find_service(list_resp.json()["data"], "svc-bound-event")
    assert item["can_delete"] is False

    del_resp = await async_client.delete(
        f"/notifications/services/{sid}",
        headers=_auth_header(98103),
    )
    assert del_resp.status_code == 409
    assert "notification events" in del_resp.json()["message"].lower()


@pytest.mark.asyncio
async def test_list_and_delete_blocked_by_engagement_notification(
    async_client, test_db_session
):
    from tests.helpers.engagement_types import engagement_type_id

    await _seed_employee(test_db_session, user_id=98104, employee_id=98104)
    sid = await _seed_service(
        test_db_session, service_key="svc-bound-eng", display_name="Bound Engagement"
    )
    type_id = await engagement_type_id(test_db_session, "bio_ai")
    eid = 98104
    await test_db_session.execute(
        text(
            """
            INSERT INTO engagements (
                engagement_id, engagement_name, engagement_code, engagement_type,
                assessment_package_id, diagnostic_package_id, city, slot_duration,
                start_date, end_date, status, blood_collection_type, payment_type
            )
            VALUES (
                :eid, 'Del Gate Eng', 'E98104', :etype, 1, 1, 'BLR', 20,
                '2026-12-01', '2026-12-01', 3, 'camp_collection', 'paid_by_group'
            )
            ON CONFLICT (engagement_id) DO NOTHING
            """
        ),
        {"eid": eid, "etype": type_id},
    )
    await test_db_session.execute(
        text(
            """
            INSERT INTO engagement_notifications (
                engagement_id, event_code, recipient_type, delivery_channel,
                condition_key, notification_services
            )
            VALUES (
                :eid, 'test.delete_eng', 'user', 'whatsapp', 'default',
                CAST(:services AS jsonb)
            )
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "eid": eid,
            "services": json.dumps([{"service_key": "svc-bound-eng"}]),
        },
    )
    await test_db_session.commit()

    list_resp = await async_client.get(
        "/notifications/services",
        headers=_auth_header(98104),
    )
    item = _find_service(list_resp.json()["data"], "svc-bound-eng")
    assert item["can_delete"] is False

    del_resp = await async_client.delete(
        f"/notifications/services/{sid}",
        headers=_auth_header(98104),
    )
    assert del_resp.status_code == 409
    assert "notification events" in del_resp.json()["message"].lower()


@pytest.mark.asyncio
async def test_list_and_delete_blocked_by_notification_logs(async_client, test_db_session):
    await _seed_employee(test_db_session, user_id=98105, employee_id=98105)
    sid = await _seed_service(
        test_db_session, service_key="svc-has-logs", display_name="Has Logs"
    )
    test_db_session.add(
        Notification(
            service_key="svc-has-logs",
            status="sent",
            channel="whatsapp",
            user={"user_ids": [98105]},
            message="log row",
            dispatched_at=datetime.now(timezone.utc),
        )
    )
    await test_db_session.commit()

    list_resp = await async_client.get(
        "/notifications/services",
        headers=_auth_header(98105),
    )
    item = _find_service(list_resp.json()["data"], "svc-has-logs")
    assert item["can_delete"] is False

    del_resp = await async_client.delete(
        f"/notifications/services/{sid}",
        headers=_auth_header(98105),
    )
    assert del_resp.status_code == 409
    assert "sent notifications" in del_resp.json()["message"].lower()