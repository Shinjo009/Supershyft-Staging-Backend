"""Tests for test-group package_for audience and package list inclusive filters."""

from __future__ import annotations

import pytest

from modules.diagnostics.models import (
    DiagnosticPackage,
    DiagnosticPackageGroup,
    DiagnosticPackageTestGroup,
    DiagnosticProfileGroup,
    DiagnosticTestGroup,
    DiagnosticTestGroupTest,
    HealthParameter,
    ParameterType,
)
from tests.helpers.auth import employee_auth_header, seed_employee


@pytest.mark.asyncio
async def test_assign_public_only_test_group_rejected(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=950, role="admin")
    profile = DiagnosticProfileGroup()
    test_db_session.add(profile)
    await test_db_session.flush()
    tg = DiagnosticTestGroup(
        profile_group_id=profile.profile_group_id,
        is_default_for_group=True,
        group_name="Public only",
        group_key="public_only_tg",
        package_for="public",
    )
    pkg_group = DiagnosticPackageGroup()
    test_db_session.add(pkg_group)
    await test_db_session.flush()
    package = DiagnosticPackage(
        package_group_id=pkg_group.package_group_id,
        is_default_for_group=True,
        package_name="Pkg",
        status="active",
        package_for="public",
    )
    test_db_session.add(tg)
    test_db_session.add(package)
    await test_db_session.commit()

    response = await async_client.post(
        f"/diagnostic-packages/{package.diagnostic_package_id}/test-groups",
        headers=employee_auth_header(950),
        json={"group_ids": [tg.group_id]},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "DIAGNOSTIC_TEST_GROUP_PACKAGE_FOR_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_package_list_public_includes_both(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=951, role="admin")
    for idx, pf in enumerate(("public", "both")):
        grp = DiagnosticPackageGroup()
        test_db_session.add(grp)
        await test_db_session.flush()
        test_db_session.add(
            DiagnosticPackage(
                package_group_id=grp.package_group_id,
                is_default_for_group=True,
                package_name=f"Pkg {pf}",
                status="active",
                package_for=pf,
            )
        )
    await test_db_session.commit()

    response = await async_client.get(
        "/diagnostic-packages/groups",
        headers=employee_auth_header(951),
        params={"package_for": "public", "type": "public_package"},
    )
    assert response.status_code == 200
    names = {row["package_name"] for row in response.json()["data"]}
    assert "Pkg public" in names
    assert "Pkg both" in names


@pytest.mark.asyncio
async def test_catalog_test_set_conflict(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=952, role="admin")
    hp = HealthParameter(
        test_name="HbA1c",
        parameter_type=ParameterType.TEST,
        is_available=True,
    )
    test_db_session.add(hp)
    await test_db_session.flush()

    async def make_group(name: str, key: str) -> DiagnosticTestGroup:
        profile = DiagnosticProfileGroup()
        test_db_session.add(profile)
        await test_db_session.flush()
        group = DiagnosticTestGroup(
            profile_group_id=profile.profile_group_id,
            is_default_for_group=True,
            group_name=name,
            group_key=key,
            package_for="public",
        )
        test_db_session.add(group)
        await test_db_session.flush()
        test_db_session.add(DiagnosticTestGroupTest(group_id=group.group_id, test_id=hp.test_id, display_order=1))
        await test_db_session.flush()
        return group

    await make_group("First", "first_set")
    await test_db_session.commit()

    create = await async_client.post(
        "/diagnostic-test-groups",
        headers=employee_auth_header(952),
        json={"group_name": "Second", "group_key": "second_set", "package_for": "public"},
    )
    assert create.status_code in (200, 201)
    group_id = create.json()["data"]["group_id"]

    assign = await async_client.post(
        f"/diagnostic-test-groups/{group_id}/tests",
        headers=employee_auth_header(952),
        json={"test_ids": [hp.test_id]},
    )
    assert assign.status_code == 400
    assert assign.json()["error_code"] == "DIAGNOSTIC_TEST_GROUP_TEST_SET_CONFLICT"
    assert "suggested_group" in assign.json()


@pytest.mark.asyncio
async def test_catalog_test_set_join_variant_when_different_profile(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=953, role="admin")
    hp = HealthParameter(test_name="Lipid", parameter_type=ParameterType.TEST, is_available=True)
    test_db_session.add(hp)
    await test_db_session.flush()

    profile_a = DiagnosticProfileGroup()
    profile_b = DiagnosticProfileGroup()
    test_db_session.add_all([profile_a, profile_b])
    await test_db_session.flush()

    healthians = DiagnosticTestGroup(
        profile_group_id=profile_a.profile_group_id,
        is_default_for_group=True,
        group_name="Lipid H",
        group_key="lipid_h",
        diagnostic_provider="healthians",
        package_for="public",
    )
    test_db_session.add(healthians)
    await test_db_session.flush()
    test_db_session.add(
        DiagnosticTestGroupTest(group_id=healthians.group_id, test_id=hp.test_id, display_order=1)
    )

    newcomer = DiagnosticTestGroup(
        profile_group_id=profile_b.profile_group_id,
        is_default_for_group=True,
        group_name="Lipid Orange",
        group_key="lipid_o",
        diagnostic_provider="orange_health",
        package_for="public",
    )
    test_db_session.add(newcomer)
    await test_db_session.flush()
    await test_db_session.commit()

    assign = await async_client.post(
        f"/diagnostic-test-groups/{newcomer.group_id}/tests",
        headers=employee_auth_header(953),
        json={"test_ids": [hp.test_id]},
    )
    assert assign.status_code == 400
    body = assign.json()
    assert body["error_code"] == "DIAGNOSTIC_TEST_GROUP_TEST_SET_EXISTS"
    assert body.get("recommended_action") == "join_variant"
    assert body.get("existing_group_id") == healthians.group_id


@pytest.mark.asyncio
async def test_assign_null_provider_test_group_to_lab_package(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=954, role="admin")
    pkg_group = DiagnosticPackageGroup()
    test_db_session.add(pkg_group)
    await test_db_session.flush()
    package = DiagnosticPackage(
        package_group_id=pkg_group.package_group_id,
        is_default_for_group=True,
        package_name="Orange pkg",
        diagnostic_provider="orange_health",
        status="active",
        package_for="public",
    )
    profile = DiagnosticProfileGroup()
    test_db_session.add(profile)
    await test_db_session.flush()
    tg = DiagnosticTestGroup(
        profile_group_id=profile.profile_group_id,
        is_default_for_group=True,
        group_name="Generic panel",
        group_key="generic_panel",
        diagnostic_provider=None,
        package_for="both",
    )
    test_db_session.add(package)
    test_db_session.add(tg)
    await test_db_session.commit()

    response = await async_client.post(
        f"/diagnostic-packages/{package.diagnostic_package_id}/test-groups",
        headers=employee_auth_header(954),
        json={"group_ids": [tg.group_id]},
    )
    assert response.status_code in (200, 201)
    assert tg.group_id in response.json()["data"]["added_group_ids"]