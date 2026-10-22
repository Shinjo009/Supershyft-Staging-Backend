"""Tests for event catalog and event-bindings CRUD."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.helpers.auth import employee_auth_header, seed_employee


async def _seed_service(test_db_session, *, service_key: str = "welcome-whatsapp-test"):
    await test_db_session.execute(
        text(
            "INSERT INTO notification_services "
            "(service_key, display_name, channel, is_active, template_name, template_variables) "
            "VALUES (:sk, 'Test', 'whatsapp', true, 'test_template', '[]'::jsonb) "
            "ON CONFLICT (service_key) DO NOTHING"
        ),
        {"sk": service_key},
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_events_catalog_endpoint(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=9701, role="admin")
    response = await async_client.get(
        "/notifications/events/catalog",
        headers=employee_auth_header(9701),
    )
    assert response.status_code == 200
    body = response.json()
    codes = {item["event_code"] for item in body["data"]}
    assert "onboarding" in codes
    assert "otp_whatsapp" in codes
    assert "consultation_rescheduled" in codes


@pytest.mark.asyncio
async def test_event_bindings_crud(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=9702, role="admin")
    await _seed_service(test_db_session, service_key="binding-test-wa")
    headers = employee_auth_header(9702)
    await test_db_session.execute(
        text(
            "DELETE FROM notification_events "
            "WHERE event_code = 'otp_whatsapp' AND recipient_type = 'participant'"
        )
    )
    await test_db_session.commit()

    create = await async_client.post(
        "/notifications/event-bindings",
        headers=headers,
        json={
            "event_code": "otp_whatsapp",
            "event_name": "OTP WhatsApp",
            "recipient_type": "participant",
            "notification_services": [{"service_key": "binding-test-wa"}],
        },
    )
    assert create.status_code == 201
    binding_id = create.json()["data"]["id"]

    listed = await async_client.get("/notifications/event-bindings", headers=headers)
    assert listed.status_code == 200
    assert any(row["id"] == binding_id for row in listed.json()["data"])

    updated = await async_client.put(
        f"/notifications/event-bindings/{binding_id}",
        headers=headers,
        json={"event_name": "OTP WA Updated"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["event_name"] == "OTP WA Updated"

    deleted = await async_client.delete(
        f"/notifications/event-bindings/{binding_id}",
        headers=headers,
    )
    assert deleted.status_code == 200


@pytest.mark.asyncio
async def test_event_binding_invalid_event_code(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=9703, role="admin")
    await _seed_service(test_db_session, service_key="binding-test-wa-2")
    response = await async_client.post(
        "/notifications/event-bindings",
        headers=employee_auth_header(9703),
        json={
            "event_code": "not_in_catalog",
            "event_name": "Bad",
            "recipient_type": "participant",
            "notification_services": [{"service_key": "binding-test-wa-2"}],
        },
    )
    assert response.status_code == 400
