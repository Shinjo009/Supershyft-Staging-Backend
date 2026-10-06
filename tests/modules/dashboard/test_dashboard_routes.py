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
    assert "operations" in data
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
