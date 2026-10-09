"""Route tests for diagnostic test group list/read auth (employee or user JWT)."""

from __future__ import annotations

import pytest

from modules.diagnostics.models import DiagnosticTestGroup
from modules.users.models import User
from tests.helpers.auth import employee_auth_header, seed_employee, user_auth_header


@pytest.mark.asyncio
async def test_employee_can_list_diagnostic_test_groups(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=910, role="admin")
    test_db_session.add(
        DiagnosticTestGroup(group_name="Lipid Panel", group_key="lipid_panel_list_test")
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/diagnostic-test-groups",
        headers=employee_auth_header(910),
    )
    assert response.status_code == 200
    keys = {row["group_key"] for row in response.json()["data"]}
    assert "lipid_panel_list_test" in keys


@pytest.mark.asyncio
async def test_user_can_list_diagnostic_test_groups(async_client, test_db_session):
    test_db_session.add(User(user_id=8110, phone="8110000010", age=30, status="active"))
    test_db_session.add(
        DiagnosticTestGroup(group_name="Thyroid", group_key="thyroid_list_test")
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/diagnostic-test-groups",
        headers=user_auth_header(8110),
    )
    assert response.status_code == 200
    keys = {row["group_key"] for row in response.json()["data"]}
    assert "thyroid_list_test" in keys


@pytest.mark.asyncio
async def test_list_diagnostic_test_groups_requires_auth(async_client):
    response = await async_client.get("/diagnostic-test-groups")
    assert response.status_code == 401
    assert response.json() == {"error_code": "AUTH_FAILED", "message": "Authentication failed"}


@pytest.mark.asyncio
async def test_employee_can_list_group_tests(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=911, role="admin")
    group = DiagnosticTestGroup(group_name="CBC", group_key="cbc_tests_test")
    test_db_session.add(group)
    await test_db_session.commit()
    await test_db_session.refresh(group)

    response = await async_client.get(
        f"/diagnostic-test-groups/{group.group_id}/tests",
        headers=employee_auth_header(911),
    )
    assert response.status_code == 200
    assert response.json()["data"] == []


@pytest.mark.asyncio
async def test_user_can_list_group_tests(async_client, test_db_session):
    test_db_session.add(User(user_id=8111, phone="8110000011", age=30, status="active"))
    group = DiagnosticTestGroup(group_name="Vitamin D", group_key="vitd_tests_test")
    test_db_session.add(group)
    await test_db_session.commit()
    await test_db_session.refresh(group)

    response = await async_client.get(
        f"/diagnostic-test-groups/{group.group_id}/tests",
        headers=user_auth_header(8111),
    )
    assert response.status_code == 200
    assert response.json()["data"] == []


@pytest.mark.asyncio
async def test_list_group_tests_requires_auth(async_client, test_db_session):
    group = DiagnosticTestGroup(group_name="Empty", group_key="empty_auth_test")
    test_db_session.add(group)
    await test_db_session.commit()
    await test_db_session.refresh(group)

    response = await async_client.get(f"/diagnostic-test-groups/{group.group_id}/tests")
    assert response.status_code == 401
    assert response.json() == {"error_code": "AUTH_FAILED", "message": "Authentication failed"}
