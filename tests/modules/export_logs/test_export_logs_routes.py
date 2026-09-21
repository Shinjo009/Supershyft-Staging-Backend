"""Integration tests for export log create and list APIs."""

from __future__ import annotations

import pytest

from modules.employee.models import (
    EmployeeCategoryPermission,
    EmployeeTaskPermission,
    PermissionCategory,
)
from modules.employee.permissions import PERMISSION_CATEGORY_KEYS
from tests.helpers.auth import (
    employee_auth_header,
    partner_auth_header,
    seed_employee,
    seed_partner,
    user_auth_header,
)

_VALID_PAYLOAD = {
    "reason": "Need camp attendance sheet",
    "export_type": "participants",
    "export_format": "csv",
    "source_kind": "engagement",
    "source_id": "42",
    "row_count": 4,
    "details": {
        "source_name": "Wellness Camp 2026",
        "engagement_name": "Wellness Camp 2026",
    },
}


def _headers(employee_id: int) -> dict[str, str]:
    return employee_auth_header(employee_id)


async def _ensure_category(db, key: str) -> None:
    if await db.get(PermissionCategory, key) is None:
        db.add(
            PermissionCategory(
                category_key=key,
                display_name=key.replace("_", " ").title(),
                description="Test category",
                display_order=sorted(PERMISSION_CATEGORY_KEYS).index(key) + 1,
                is_active=True,
            )
        )
        await db.flush()


@pytest.mark.asyncio
async def test_create_export_log_requires_reason(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=6101, role="admin")
    payload = dict(_VALID_PAYLOAD)
    payload["reason"] = "   "
    response = await async_client.post(
        "/export-logs",
        headers=_headers(6101),
        json=payload,
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_create_export_log_stores_employee_from_jwt(async_client, test_db_session):
    await seed_employee(
        test_db_session,
        employee_id=6102,
        role="admin",
        name="Log Actor",
    )
    response = await async_client.post(
        "/export-logs",
        headers=_headers(6102),
        json=_VALID_PAYLOAD,
    )
    assert response.status_code == 200
    export_log_id = response.json()["data"]["export_log_id"]
    assert export_log_id >= 1

    listed = await async_client.get("/employees/export-logs", headers=_headers(6102))
    assert listed.status_code == 200
    rows = listed.json()["data"]
    assert rows
    row = next(item for item in rows if item["export_log_id"] == export_log_id)
    assert row["employee_id"] == 6102
    assert row["partner_id"] is None
    assert row["actor_name"] == "Log Actor"
    assert row["actor_role"] == "admin"
    assert row["reason"] == "Need camp attendance sheet"
    assert row["export_type"] == "participants"
    assert row["export_format"] == "csv"
    assert row["source_kind"] == "engagement"
    assert row["source_id"] == "42"
    assert row["row_count"] == 4
    assert row["details"]["source_name"] == "Wellness Camp 2026"
    assert row["details"]["engagement_name"] == "Wellness Camp 2026"


@pytest.mark.asyncio
async def test_list_export_logs_search_matches_source_name(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=6106, role="admin")
    created = await async_client.post(
        "/export-logs",
        headers=_headers(6106),
        json={
            **_VALID_PAYLOAD,
            "source_kind": "organization",
            "source_id": "88",
            "details": {
                "source_name": "Acme Health Pvt Ltd",
                "organization_name": "Acme Health Pvt Ltd",
            },
        },
    )
    assert created.status_code == 200

    listed = await async_client.get(
        "/employees/export-logs?search=Acme%20Health",
        headers=_headers(6106),
    )
    assert listed.status_code == 200
    rows = listed.json()["data"]
    assert any(row["source_id"] == "88" for row in rows)
    miss = await async_client.get(
        "/employees/export-logs?search=no-such-org",
        headers=_headers(6106),
    )
    assert miss.status_code == 200
    assert all(row["source_id"] != "88" for row in miss.json()["data"])


@pytest.mark.asyncio
async def test_list_export_logs_newest_first(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=6103, role="admin")
    first = await async_client.post(
        "/export-logs",
        headers=_headers(6103),
        json={**_VALID_PAYLOAD, "reason": "First export reason"},
    )
    second = await async_client.post(
        "/export-logs",
        headers=_headers(6103),
        json={**_VALID_PAYLOAD, "reason": "Second export reason"},
    )
    assert first.status_code == 200
    assert second.status_code == 200

    listed = await async_client.get("/employees/export-logs?limit=10", headers=_headers(6103))
    assert listed.status_code == 200
    reasons = [row["reason"] for row in listed.json()["data"] if row["employee_id"] == 6103]
    assert reasons[0] == "Second export reason"
    assert "First export reason" in reasons


@pytest.mark.asyncio
async def test_inferior_admin_without_export_logs_cannot_list(async_client, test_db_session):
    await seed_employee(
        test_db_session,
        employee_id=6104,
        role="inferior_admin",
    )
    await _ensure_category(test_db_session, "employees")
    test_db_session.add(
        EmployeeCategoryPermission(
            employee_id=6104,
            category_key="employees",
            can_view=True,
            can_edit=False,
        )
    )
    test_db_session.add(
        EmployeeTaskPermission(
            employee_id=6104,
            category_key="employees",
            task_key="directory",
            can_view=True,
            can_edit=False,
        )
    )
    await test_db_session.commit()

    response = await async_client.get("/employees/export-logs", headers=_headers(6104))
    assert response.status_code == 403
    assert response.json()["error_code"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_partner_can_create_export_log(async_client, test_db_session):
    partner = await seed_partner(
        test_db_session,
        partner_id=7101,
        role="organization_manager",
        name="Org Manager",
        phone="9100007101",
    )
    response = await async_client.post(
        "/export-logs",
        headers=partner_auth_header(partner.partner_id),
        json=_VALID_PAYLOAD,
    )
    assert response.status_code == 200

    await seed_employee(test_db_session, employee_id=6105, role="admin")
    listed = await async_client.get("/employees/export-logs", headers=_headers(6105))
    assert listed.status_code == 200
    row = next(
        item
        for item in listed.json()["data"]
        if item["export_log_id"] == response.json()["data"]["export_log_id"]
    )
    assert row["partner_id"] == partner.partner_id
    assert row["employee_id"] is None
    assert row["actor_name"] == "Org Manager"
    assert row["actor_role"] == "organization_manager"


@pytest.mark.asyncio
async def test_user_cannot_create_export_log(async_client, test_db_session):
    from modules.users.models import User

    test_db_session.add(User(user_id=8101, phone="8101000000", age=30, status="active"))
    await test_db_session.commit()
    response = await async_client.post(
        "/export-logs",
        headers=user_auth_header(8101),
        json=_VALID_PAYLOAD,
    )
    assert response.status_code in {401, 403}
