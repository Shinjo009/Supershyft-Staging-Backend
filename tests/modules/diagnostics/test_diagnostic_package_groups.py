"""Tests for diagnostic package groups list and default-for-group flag."""

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
from tests.helpers.auth import employee_auth_header, seed_employee


async def _add_package_with_group(session, *, is_default_for_group: bool = False, **fields) -> DiagnosticPackage:
    group = DiagnosticPackageGroup()
    session.add(group)
    await session.flush()
    pkg = DiagnosticPackage(
        package_group_id=group.package_group_id,
        is_default_for_group=is_default_for_group,
        **fields,
    )
    session.add(pkg)
    await session.commit()
    await session.refresh(pkg)
    return pkg


@pytest.mark.asyncio
async def test_public_list_diagnostic_package_groups(async_client, test_db_session):
    healthians = await _add_package_with_group(
        test_db_session,
        package_name="Group Core",
        diagnostic_provider="healthians",
        price=1999,
        status="active",
        package_for="public",
        is_default_for_group=True,
    )
    orange = await _add_package_with_group(
        test_db_session,
        package_name="Group Core Orange",
        diagnostic_provider="orange_health",
        price=2499,
        status="active",
        package_for="public",
        is_default_for_group=False,
    )
    orange.package_group_id = healthians.package_group_id
    orange.is_default_for_group = False
    test_db_session.add(orange)
    await test_db_session.commit()

    response = await async_client.get("/diagnostic-packages/groups")
    assert response.status_code == 200
    rows = response.json()["data"]
    match = next(row for row in rows if row["diagnostic_package_id"] == healthians.diagnostic_package_id)
    assert match["package_group"]["healthians"] == healthians.diagnostic_package_id
    assert match["package_group"]["orange_health"] == orange.diagnostic_package_id
    assert match["price"] == 1999.0
    assert "same_packages" not in match
    assert "unmapped_test_count" not in match
    assert "has_unmapped_tests" in match


@pytest.mark.asyncio
async def test_groups_route_does_not_shadow_detail(async_client, test_db_session):
    pkg = await _add_package_with_group(
        test_db_session,
        package_name="Detail Pkg",
        status="active",
        package_for="public",
        is_default_for_group=True,
    )
    detail = await async_client.get(f"/diagnostic-packages/{pkg.diagnostic_package_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["package_name"] == "Detail Pkg"


@pytest.mark.asyncio
async def test_set_default_for_group_via_update(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=920, role="admin")
    healthians = await _add_package_with_group(
        test_db_session,
        package_name="Switch Default",
        diagnostic_provider="healthians",
        price=1000,
        status="active",
        package_for="public",
        is_default_for_group=True,
    )
    orange = DiagnosticPackage(
        package_name="Switch Default Orange",
        diagnostic_provider="orange_health",
        price=2000,
        status="active",
        package_for="public",
        package_group_id=healthians.package_group_id,
        is_default_for_group=False,
    )
    test_db_session.add(orange)
    await test_db_session.commit()
    await test_db_session.refresh(orange)

    response = await async_client.put(
        f"/diagnostic-packages/{orange.diagnostic_package_id}",
        headers=employee_auth_header(920),
        json={"is_default_for_group": True},
    )
    assert response.status_code == 200
    assert response.json()["data"]["is_default_for_group"] is True

    groups = await async_client.get(
        "/diagnostic-packages/groups",
        params={"include_inactive": True, "type": "public_package"},
        headers=employee_auth_header(920),
    )
    row = next(
        item for item in groups.json()["data"] if item["diagnostic_package_id"] == orange.diagnostic_package_id
    )
    assert row["price"] == 2000.0


@pytest.mark.asyncio
async def test_per_package_list_still_returns_all_skus(async_client, test_db_session):
    healthians = await _add_package_with_group(
        test_db_session,
        package_name="All SKUs",
        diagnostic_provider="healthians",
        status="active",
        package_for="public",
        is_default_for_group=True,
    )
    orange = DiagnosticPackage(
        package_name="All SKUs Orange",
        diagnostic_provider="orange_health",
        status="active",
        package_for="public",
        package_group_id=healthians.package_group_id,
        is_default_for_group=False,
    )
    test_db_session.add(orange)
    await test_db_session.commit()
    await test_db_session.refresh(orange)

    response = await async_client.get("/diagnostic-packages")
    assert response.status_code == 200
    ids = {row["diagnostic_package_id"] for row in response.json()["data"]}
    assert healthians.diagnostic_package_id in ids
    assert orange.diagnostic_package_id in ids


async def _assign_test_group(session, package: DiagnosticPackage, *, group_key: str = "core_panel") -> DiagnosticTestGroup:
    test = HealthParameter(test_name="Haemoglobin", parameter_type="test")
    group = DiagnosticTestGroup(group_name="Core panel", group_key=group_key)
    session.add_all([test, group])
    await session.flush()
    session.add(
        DiagnosticPackageTestGroup(
            diagnostic_package_id=package.diagnostic_package_id,
            group_id=group.group_id,
            display_order=1,
        )
    )
    session.add(
        DiagnosticTestGroupTest(
            group_id=group.group_id,
            test_id=test.test_id,
            display_order=0,
        )
    )
    await session.commit()
    await session.refresh(group)
    return group


@pytest.mark.asyncio
async def test_create_joining_package_copies_test_groups(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=921, role="admin")
    healthians = await _add_package_with_group(
        test_db_session,
        package_name="Copy Groups Core",
        diagnostic_provider="healthians",
        status="active",
        package_for="public",
        is_default_for_group=True,
    )
    source_group = await _assign_test_group(test_db_session, healthians, group_key="copy_source_group")

    create_resp = await async_client.post(
        "/diagnostic-packages",
        headers=employee_auth_header(921),
        json={
            "package_name": "Copy Groups Core",
            "diagnostic_provider": "orange_health",
            "package_for": "public",
            "same_as_package_id": healthians.diagnostic_package_id,
            "copy_test_groups_from_package_id": healthians.diagnostic_package_id,
        },
    )
    assert create_resp.status_code in (200, 201)
    new_id = create_resp.json()["data"]["diagnostic_package_id"]

    source_tests = await async_client.get(
        f"/diagnostic-packages/{healthians.diagnostic_package_id}/tests",
        headers=employee_auth_header(921),
    )
    new_tests = await async_client.get(
        f"/diagnostic-packages/{new_id}/tests",
        headers=employee_auth_header(921),
    )
    assert source_tests.status_code == 200
    assert new_tests.status_code == 200
    source_groups = source_tests.json()["data"]["groups"]
    new_groups = new_tests.json()["data"]["groups"]
    assert len(source_groups) == 1
    assert len(new_groups) == 1
    assert source_groups[0]["group_id"] == source_group.group_id
    assert new_groups[0]["group_id"] != source_group.group_id
    assert new_groups[0]["group_name"] == source_groups[0]["group_name"]
