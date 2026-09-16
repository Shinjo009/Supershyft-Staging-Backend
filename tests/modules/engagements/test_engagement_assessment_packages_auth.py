"""Regression: admin employee JWTs can list/assign engagement assessment packages."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.helpers.auth import employee_auth_header, seed_employee, user_auth_header


async def _seed_employee(test_db_session, *, employee_id: int = 1, role: str = "admin"):
    await seed_employee(test_db_session, employee_id=employee_id, role=role)


async def _engagement_type_id(test_db_session, code: str = "bio_ai") -> int:
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_types (code, display_name, is_active) "
            "VALUES (:code, :dn, true) "
            "ON CONFLICT (code) DO UPDATE SET is_active = true"
        ),
        {"code": code, "dn": code},
    )
    await test_db_session.commit()
    row = (
        await test_db_session.execute(
            text("SELECT id FROM engagement_types WHERE code = :code"),
            {"code": code},
        )
    ).one()
    return int(row[0])


async def _seed_running_engagement(test_db_session, *, engagement_id: int = 9301, package_id: int = 2):
    type_id = await _engagement_type_id(test_db_session)
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, package_name, diagnostic_provider, status) "
            "VALUES (1, 'Test Diagnostic', 'test_provider', 'active') ON CONFLICT (diagnostic_package_id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, assessment_type_code, status) "
            "VALUES (:pid, 'METSIGHTS_PRO', 'Metsights Pro', '2', 'active') "
            "ON CONFLICT (package_id) DO UPDATE SET "
            "package_code = EXCLUDED.package_code, "
            "assessment_type_code = EXCLUDED.assessment_type_code, "
            "status = EXCLUDED.status"
        ),
        {"pid": package_id},
    )
    await test_db_session.execute(
        text(
            "INSERT INTO engagements (engagement_id, engagement_name, engagement_code, engagement_type, "
            "assessment_package_id, diagnostic_package_id, city, slot_duration, start_date, end_date, "
            "status, organization_id) "
            "VALUES (:eid, 'Camp', 'ENG9301', :etype, :pid, 1, 'BLR', 20, "
            "'2026-02-01', '2026-02-28', 'running', NULL)"
        ),
        {"eid": engagement_id, "pid": package_id, "etype": type_id},
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_list_assessment_packages_requires_auth(async_client):
    response = await async_client.get("/engagements/9301/assessment-packages")
    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTH_FAILED"


@pytest.mark.asyncio
async def test_list_assessment_packages_accepts_employee_jwt(async_client, test_db_session):
    await _seed_employee(test_db_session, employee_id=1)
    await _seed_running_engagement(test_db_session)

    response = await async_client.get(
        "/engagements/9301/assessment-packages",
        headers=employee_auth_header(1),
    )
    assert response.status_code == 200
    assert response.json()["data"] == []


@pytest.mark.asyncio
async def test_list_assessment_packages_accepts_participant_user_jwt(async_client, test_db_session):
    await _seed_running_engagement(test_db_session)
    await test_db_session.execute(
        text(
            "INSERT INTO users (user_id, first_name, last_name, age, phone, status) "
            "VALUES (5301, 'Riya', 'Sharma', 33, '+919876543211', 'active')"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_participants "
            "(engagement_id, user_id, engagement_date, slot_start_time, booked_by_user_id) "
            "VALUES (9301, 5301, '2026-02-10', '09:00:00', 5301)"
        )
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/engagements/9301/assessment-packages",
        headers=user_auth_header(5301),
    )
    assert response.status_code == 200
    assert response.json()["data"] == []


@pytest.mark.asyncio
async def test_list_assessment_packages_rejects_non_participant_user(async_client, test_db_session):
    await _seed_running_engagement(test_db_session)
    await test_db_session.execute(
        text(
            "INSERT INTO users (user_id, first_name, last_name, age, phone, status) "
            "VALUES (5302, 'Other', 'User', 40, '+919876543212', 'active')"
        )
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/engagements/9301/assessment-packages",
        headers=user_auth_header(5302),
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_add_assessment_package_accepts_employee_jwt(async_client, test_db_session):
    await _seed_employee(test_db_session, employee_id=1)
    await _seed_running_engagement(test_db_session)
    await test_db_session.execute(
        text(
            "INSERT INTO users (user_id, first_name, last_name, age, phone, status) "
            "VALUES (5303, 'Sam', 'Lee', 28, '+919876543213', 'active')"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_participants "
            "(engagement_id, user_id, engagement_date, slot_start_time, booked_by_user_id) "
            "VALUES (9301, 5303, '2026-02-10', '09:00:00', 5303)"
        )
    )
    await test_db_session.commit()

    response = await async_client.post(
        "/engagements/9301/assessment-packages",
        headers=employee_auth_header(1),
        json={"package_code": "METSIGHTS_PRO"},
    )
    assert response.status_code == 201
    body = response.json()["data"]
    assert body["package_code"] == "METSIGHTS_PRO"
    assert len(body["created"]) == 1
    assert body["created"][0]["user_id"] == 5303
