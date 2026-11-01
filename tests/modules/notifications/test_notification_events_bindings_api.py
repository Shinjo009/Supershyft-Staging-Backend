"""Tests for notification event catalog and global bindings API."""

from __future__ import annotations

import pytest
from sqlalchemy import text


def _auth_header(employee_id: int) -> dict[str, str]:
    from tests.helpers.auth import employee_auth_header

    return employee_auth_header(employee_id)


async def _seed_employee(test_db_session, *, user_id: int, employee_id: int):
    from modules.employee.models import Employee
    from modules.users.models import User

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


async def _seed_service(test_db_session, *, service_key: str = "test-binding-svc"):
    from tests.modules.notifications.notification_test_seeds import upsert_notification_service

    await upsert_notification_service(test_db_session, service_key=service_key, channel="whatsapp")
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_catalog_requires_employee(async_client):
    response = await async_client.get("/notification-events/catalog")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_catalog_returns_groups(async_client, test_db_session):
    await _seed_employee(test_db_session, user_id=9701, employee_id=9701)
    response = await async_client.get(
        "/notification-events/catalog",
        headers=_auth_header(9701),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    codes = {
        event["event_code"]
        for group in data["groups"]
        for event in group["events"]
    }
    assert "auth.otp.sent" in codes
    assert "onboarding.completed" in codes
    assert "collection.confirmed" in codes
    assert "shared_variable_bags" in data or data.get("shared_variable_bags") is not None


@pytest.mark.asyncio
async def test_bindings_crud_and_validation(async_client, test_db_session):
    await _seed_employee(test_db_session, user_id=9702, employee_id=9702)
    await _seed_service(test_db_session, service_key="binding-svc-9702")
    headers = _auth_header(9702)

    bad = await async_client.post(
        "/notification-events/bindings",
        headers=headers,
        json={
            "event_code": "not.a.real.event",
            "recipient_type": "participant",
            "notification_services": ["binding-svc-9702"],
        },
    )
    assert bad.status_code == 400

    bad_recipient = await async_client.post(
        "/notification-events/bindings",
        headers=headers,
        json={
            "event_code": "auth.otp.sent",
            "recipient_type": "booker",
            "notification_services": ["binding-svc-9702"],
        },
    )
    assert bad_recipient.status_code == 400

    create = await async_client.post(
        "/notification-events/bindings",
        headers=headers,
        json={
            "event_code": "auth.otp.sent",
            "recipient_type": "participant",
            "notification_services": ["binding-svc-9702"],
        },
    )
    assert create.status_code == 200
    binding_id = create.json()["data"]["id"]

    listed = await async_client.get("/notification-events/bindings", headers=headers)
    assert listed.status_code == 200
    assert any(row["id"] == binding_id for row in listed.json()["data"])

    deleted = await async_client.delete(
        f"/notification-events/bindings/{binding_id}",
        headers=headers,
    )
    assert deleted.status_code == 200


@pytest.mark.asyncio
async def test_migration_0184_columns_exist(test_db_session):
    result = await test_db_session.execute(
        text(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'notification_services' AND column_name = 'template_name'
            UNION ALL
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'notifications' AND column_name = 'queue_id'
            UNION ALL
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'engagement_notifications' AND column_name = 'event_code'
            """
        )
    )
    cols = {row[0] for row in result.all()}
    assert "template_name" in cols
    assert "queue_id" in cols
    assert "event_code" in cols

    table = await test_db_session.execute(
        text(
            "SELECT to_regclass('public.notification_events')"
        )
    )
    assert table.scalar_one() is not None
