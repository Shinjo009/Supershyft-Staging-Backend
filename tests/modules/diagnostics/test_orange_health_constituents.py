"""Tests for Orange Health D2C test catalog endpoint."""

from __future__ import annotations

import pytest

from modules.diagnostics.orange_health.catalog import load_d2c_tests
from tests.helpers.auth import employee_auth_header, seed_employee


def test_load_d2c_tests_includes_known_entry():
    items = load_d2c_tests()
    assert len(items) == 577
    match = next(i for i in items if i["id"] == "10")
    assert match["name"] == "Absolute Eosinophil Count"


@pytest.mark.asyncio
async def test_get_orange_health_constituents(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=904, role="admin")

    response = await async_client.get(
        "/diagnostics/orange-health/constituents",
        headers=employee_auth_header(904),
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert len(body["constituents"]) == 577
    match = next(c for c in body["constituents"] if c["id"] == "10")
    assert match["name"] == "Absolute Eosinophil Count"
