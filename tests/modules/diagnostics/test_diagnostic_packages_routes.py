"""Route tests for diagnostic package create/update auth."""

from __future__ import annotations

import pytest

from modules.diagnostics.models import DiagnosticPackage
from modules.users.models import User
from tests.helpers.auth import employee_auth_header, seed_employee, user_auth_header


@pytest.mark.asyncio
async def test_employee_can_update_diagnostic_package(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=901, role="admin")
    pkg = DiagnosticPackage(package_name="Core+", status="active", package_for="public")
    test_db_session.add(pkg)
    await test_db_session.commit()
    await test_db_session.refresh(pkg)

    response = await async_client.put(
        f"/diagnostic-packages/{pkg.diagnostic_package_id}",
        headers=employee_auth_header(901),
        json={"package_name": "Core Updated", "minimum_price": 500.0},
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["package_name"] == "Core Updated"
    assert body["min_price"] == 500.0


@pytest.mark.asyncio
async def test_user_cannot_update_public_diagnostic_package(async_client, test_db_session):
    test_db_session.add(User(user_id=8101, phone="8101000000", age=30, status="active"))
    pkg = DiagnosticPackage(
        package_name="Public Pkg",
        status="active",
        package_for="public",
        created_by_user_id=None,
    )
    test_db_session.add(pkg)
    await test_db_session.commit()
    await test_db_session.refresh(pkg)

    response = await async_client.put(
        f"/diagnostic-packages/{pkg.diagnostic_package_id}",
        headers=user_auth_header(8101),
        json={"package_name": "Hacked"},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "FORBIDDEN"
