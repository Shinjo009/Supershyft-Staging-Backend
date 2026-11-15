"""Dashboard overview and employee /me pending_task_count."""

from __future__ import annotations

import pytest

from tests.helpers.auth import seed_employee, employee_auth_header


@pytest.mark.asyncio
async def test_dashboard_overview_returns_kpis(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8802, role="admin")
    response = await async_client.get(
        "/admin/dashboard/overview",
        headers=employee_auth_header(8802),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert "users" in data
    assert "year_stats" in data
    assert "payment_status_totals" in data
    assert "engagement_participants_total" in data
    assert "operations" not in data


@pytest.mark.asyncio
async def test_dashboard_operations_returns_ops_block(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8804, role="admin")
    response = await async_client.get(
        "/admin/dashboard/operations",
        headers=employee_auth_header(8804),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    ops = data["operations"]
    assert "engagements" in ops
    assert "participant_issues" in ops
    assert "pending_payments" in ops
    assert "failed_notifications" in ops
    assert "tickets" in ops
    assert "serviceability_issues" in ops


@pytest.mark.asyncio
async def test_employee_me_includes_pending_task_count(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8803, role="admin")
    response = await async_client.get(
        "/employees/auth/me",
        headers=employee_auth_header(8803),
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert "pending_task_count" in body
    assert isinstance(body["pending_task_count"], int)


@pytest.mark.asyncio
async def test_command_notification_health_shape(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8810, role="admin")
    response = await async_client.get(
        "/admin/dashboard/command/notification-health",
        params={"period": "all_time"},
        headers=employee_auth_header(8810),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data.keys()) >= {"sent", "failed", "pending", "total"}
    assert response.json()["meta"]["period"] == "all_time"


@pytest.mark.asyncio
async def test_command_people_registered_count_only(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8811, role="admin")
    response = await async_client.get(
        "/admin/dashboard/command/people-registered",
        params={"period": "all_time", "include_rows": "false"},
        headers=employee_auth_header(8811),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert "total" in body["meta"]
    assert isinstance(body["meta"]["total"], int)
