"""Tests for notification service admin CRUD extensions (Prompt 5)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.helpers.auth import employee_auth_header


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


@pytest.mark.asyncio
async def test_create_service_defaults_webhook_and_template_fields(async_client, test_db_session):
    await _seed_employee(test_db_session, user_id=9701, employee_id=9701)
    headers = employee_auth_header(9701)

    payload = {
        "service_key": "p5-wa-test",
        "display_name": "P5 WA Test",
        "channel": "whatsapp",
        "template_name": "camp17",
        "template_variables": {"components": []},
    }
    response = await async_client.post("/notifications/services", json=payload, headers=headers)
    assert response.status_code in (200, 201), response.text
    data = response.json()["data"]
    assert data["service_key"] == "p5-wa-test"
    assert data["webhook_path"] == "/p5-wa-test"
    assert data["template_name"] == "camp17"
    assert data["template_variables"] == {"components": []}

    list_res = await async_client.get("/notifications/services", headers=headers)
    assert list_res.status_code == 200
    row = next(r for r in list_res.json()["data"] if r["service_key"] == "p5-wa-test")
    assert row["template_name"] == "camp17"

    await test_db_session.execute(
        text("DELETE FROM notification_services WHERE service_key = 'p5-wa-test'")
    )
    await test_db_session.commit()
