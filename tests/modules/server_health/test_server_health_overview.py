"""Server health overview combines current + history."""

from __future__ import annotations

import pytest

from tests.helpers.auth import employee_auth_header, seed_employee


@pytest.mark.asyncio
async def test_server_health_overview_requires_auth(async_client):
    response = await async_client.get("/server-health/overview")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_server_health_overview_shape(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8804, role="admin")
    response = await async_client.get("/server-health/overview", headers=employee_auth_header(8804))
    assert response.status_code in (200, 503)
    if response.status_code == 200:
        body = response.json()["data"]
        assert "current" in body
        assert "history" in body
        assert isinstance(body["history"], list)
