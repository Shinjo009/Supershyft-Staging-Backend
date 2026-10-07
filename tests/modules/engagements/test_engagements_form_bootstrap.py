"""Engagements form bootstrap."""

from __future__ import annotations

import pytest

from tests.helpers.auth import seed_employee, employee_auth_header


@pytest.mark.asyncio
async def test_engagements_form_bootstrap(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8804, role="admin")
    response = await async_client.get(
        "/engagements/form-bootstrap",
        headers=employee_auth_header(8804),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert "engagement_types" in data
    assert "organizations" in data
    assert "assessment_packages" in data
    assert "diagnostic_packages" in data
    assert "notification_services" in data
    assert "expert_types" in data
