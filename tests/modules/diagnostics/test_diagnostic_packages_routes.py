"""Route tests for diagnostic package create/update auth."""

from __future__ import annotations

import pytest

from modules.diagnostics.models import (
    DiagnosticPackage,
    DiagnosticPackageGroup,
    DiagnosticPackageTestGroup,
    DiagnosticTestGroup,
    DiagnosticTestGroupTest,
    HealthParameter,
)
from modules.users.models import User
from tests.helpers.auth import employee_auth_header, seed_employee, user_auth_header


async def _add_package_with_group(session, **fields) -> DiagnosticPackage:
    group = DiagnosticPackageGroup()
    session.add(group)
    await session.flush()
    pkg = DiagnosticPackage(package_group_id=group.package_group_id, **fields)
    session.add(pkg)
    await session.commit()
    await session.refresh(pkg)
    return pkg


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


@pytest.mark.asyncio
async def test_link_packages_same_group_and_list_peers(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=902, role="admin")
    healthians = await _add_package_with_group(
        test_db_session,
        package_name="Supershyft Core",
        diagnostic_provider="healthians",
        status="active",
        package_for="public",
    )

    create_resp = await async_client.post(
        "/diagnostic-packages",
        headers=employee_auth_header(902),
        json={
            "package_name": "Supershyft Core",
            "diagnostic_provider": "orange_health",
            "package_for": "public",
            "same_as_package_id": healthians.diagnostic_package_id,
        },
    )
    assert create_resp.status_code in (200, 201)
    orange_id = create_resp.json()["data"]["diagnostic_package_id"]

    list_resp = await async_client.get(
        "/diagnostic-packages",
        headers=employee_auth_header(902),
        params={"include_inactive": True, "type": "public_package"},
    )
    assert list_resp.status_code == 200
    rows = {row["diagnostic_package_id"]: row for row in list_resp.json()["data"]}
    orange_row = rows[orange_id]
    healthians_row = rows[healthians.diagnostic_package_id]
    assert len(orange_row["same_packages"]) == 1
    assert orange_row["same_packages"][0]["diagnostic_package_id"] == healthians.diagnostic_package_id
    assert len(healthians_row["same_packages"]) == 1
    assert healthians_row["same_packages"][0]["diagnostic_package_id"] == orange_id


@pytest.mark.asyncio
async def test_same_provider_in_group_rejected(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=903, role="admin")
    first = await _add_package_with_group(
        test_db_session,
        package_name="Core A",
        diagnostic_provider="healthians",
        status="active",
        package_for="public",
    )

    link_resp = await async_client.post(
        "/diagnostic-packages",
        headers=employee_auth_header(903),
        json={
            "package_name": "Core B",
            "diagnostic_provider": "orange_health",
            "package_for": "public",
            "same_as_package_id": first.diagnostic_package_id,
        },
    )
    assert link_resp.status_code in (200, 201)
    linked_id = link_resp.json()["data"]["diagnostic_package_id"]

    conflict_resp = await async_client.post(
        "/diagnostic-packages",
        headers=employee_auth_header(903),
        json={
            "package_name": "Core C",
            "diagnostic_provider": "healthians",
            "package_for": "public",
            "same_as_package_id": linked_id,
        },
    )
    assert conflict_resp.status_code == 400
    assert conflict_resp.json()["error_code"] == "DIAGNOSTIC_PACKAGE_PROVIDER_CONFLICT"


@pytest.mark.asyncio
async def test_package_name_plus_and_about_text_multiline(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=904, role="admin")
    pkg = await _add_package_with_group(
        test_db_session,
        package_name="Basic",
        status="active",
        package_for="public",
    )

    response = await async_client.put(
        f"/diagnostic-packages/{pkg.diagnostic_package_id}",
        headers=employee_auth_header(904),
        json={
            "package_name": "Core+",
            "about_text": "Line one\nLine two\x07",
        },
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["package_name"] == "Core+"
    assert "Line one\nLine two" in body["about_text"]
    assert "\x07" not in body["about_text"]


async def _assign_tests(session, package: DiagnosticPackage, tests: list[HealthParameter], group_key: str) -> None:
    group = DiagnosticTestGroup(group_name=group_key, group_key=group_key)
    session.add(group)
    session.add_all(tests)
    await session.flush()
    session.add(
        DiagnosticPackageTestGroup(
            diagnostic_package_id=package.diagnostic_package_id,
            group_id=group.group_id,
        )
    )
    for index, test in enumerate(tests):
        session.add(
            DiagnosticTestGroupTest(
                group_id=group.group_id,
                test_id=test.test_id,
                display_order=index,
            )
        )
    await session.commit()


@pytest.mark.asyncio
async def test_list_packages_reports_unmapped_provider_test_ids(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=905, role="admin")
    healthians = await _add_package_with_group(
        test_db_session,
        package_name="Mapped Partial",
        diagnostic_provider="healthians",
        status="active",
        package_for="public",
    )
    await _assign_tests(
        test_db_session,
        healthians,
        [
            HealthParameter(
                test_name="Haemoglobin",
                parameter_type="test",
                healthians_parameter_key="135",
            ),
            HealthParameter(
                test_name="Albumin",
                parameter_type="test",
                healthians_parameter_key="  ",
                orangehealth_parameter_key="oh-albumin",
            ),
        ],
        "partial-healthians",
    )

    orange = await _add_package_with_group(
        test_db_session,
        package_name="Orange Partial",
        diagnostic_provider="orange_health",
        status="active",
        package_for="public",
    )
    await _assign_tests(
        test_db_session,
        orange,
        [
            HealthParameter(
                test_name="Glucose",
                parameter_type="test",
                healthians_parameter_key="999",
            ),
            HealthParameter(
                test_name="Creatinine",
                parameter_type="test",
                orangehealth_parameter_key="oh-creatinine",
            ),
        ],
        "partial-orange",
    )

    empty = await _add_package_with_group(
        test_db_session,
        package_name="No Tests",
        diagnostic_provider="healthians",
        status="active",
        package_for="public",
    )

    list_resp = await async_client.get(
        "/diagnostic-packages",
        headers=employee_auth_header(905),
        params={"include_inactive": True, "type": "public_package"},
    )
    assert list_resp.status_code == 200
    rows = {row["diagnostic_package_id"]: row for row in list_resp.json()["data"]}

    healthians_row = rows[healthians.diagnostic_package_id]
    assert healthians_row["no_of_tests"] == 2
    assert healthians_row["unmapped_test_count"] == 1

    orange_row = rows[orange.diagnostic_package_id]
    assert orange_row["no_of_tests"] == 2
    assert orange_row["unmapped_test_count"] == 1

    empty_row = rows[empty.diagnostic_package_id]
    assert empty_row["no_of_tests"] == 0
    assert empty_row["unmapped_test_count"] == 0
