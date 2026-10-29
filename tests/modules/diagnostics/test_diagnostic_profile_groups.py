"""Tests for diagnostic test group profile groups list and default-for-group flag."""

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
)
from tests.helpers.auth import employee_auth_header, seed_employee


async def _add_test_group_with_profile(
    session,
    *,
    is_default_for_group: bool = True,
    forked_from_group_id: int | None = None,
    **fields,
) -> DiagnosticTestGroup:
    profile = DiagnosticProfileGroup()
    session.add(profile)
    await session.flush()
    group = DiagnosticTestGroup(
        profile_group_id=profile.profile_group_id,
        is_default_for_group=is_default_for_group,
        forked_from_group_id=forked_from_group_id,
        **fields,
    )
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return group


@pytest.mark.asyncio
async def test_list_diagnostic_test_group_profiles(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=930, role="admin")
    healthians = await _add_test_group_with_profile(
        test_db_session,
        group_name="Profile Core",
        group_key="profile_core_h",
        diagnostic_provider="healthians",
        price=999,
        is_default_for_group=True,
    )
    orange = DiagnosticTestGroup(
        group_name="Profile Core Orange",
        group_key="profile_core_o",
        diagnostic_provider="orange_health",
        price=1299,
        profile_group_id=healthians.profile_group_id,
        is_default_for_group=False,
    )
    test_db_session.add(orange)
    await test_db_session.commit()
    await test_db_session.refresh(orange)

    response = await async_client.get(
        "/diagnostic-test-groups/groups",
        headers=employee_auth_header(930),
    )
    assert response.status_code == 200
    rows = response.json()["data"]
    match = next(row for row in rows if row["group_id"] == healthians.group_id)
    assert match["profile_group"]["healthians"] == healthians.group_id
    assert match["profile_group"]["orange_health"] == orange.group_id
    assert match["price"] == 999.0


@pytest.mark.asyncio
async def test_forked_groups_excluded_from_profile_list(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=931, role="admin")
    catalog = await _add_test_group_with_profile(
        test_db_session,
        group_name="Catalog Only",
        group_key="catalog_only",
        is_default_for_group=True,
    )
    fork = await _add_test_group_with_profile(
        test_db_session,
        group_name="Catalog Only Fork",
        group_key="catalog_only_fork",
        forked_from_group_id=catalog.group_id,
        is_default_for_group=True,
    )
    assert fork.group_id != catalog.group_id

    response = await async_client.get(
        "/diagnostic-test-groups/groups",
        headers=employee_auth_header(931),
    )
    ids = {row["group_id"] for row in response.json()["data"]}
    assert catalog.group_id in ids
    assert fork.group_id not in ids


@pytest.mark.asyncio
async def test_set_default_test_group_via_update(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=932, role="admin")
    healthians = await _add_test_group_with_profile(
        test_db_session,
        group_name="Switch TG Default",
        group_key="switch_tg_h",
        diagnostic_provider="healthians",
        price=500,
        is_default_for_group=True,
    )
    orange = DiagnosticTestGroup(
        group_name="Switch TG Orange",
        group_key="switch_tg_o",
        diagnostic_provider="orange_health",
        price=700,
        profile_group_id=healthians.profile_group_id,
        is_default_for_group=False,
    )
    test_db_session.add(orange)
    await test_db_session.commit()
    await test_db_session.refresh(orange)

    response = await async_client.put(
        f"/diagnostic-test-groups/{orange.group_id}",
        headers=employee_auth_header(932),
        json={"is_default_for_group": True},
    )
    assert response.status_code == 200
    assert response.json()["data"]["is_default_for_group"] is True

    groups = await async_client.get(
        "/diagnostic-test-groups/groups",
        headers=employee_auth_header(932),
    )
    row = next(item for item in groups.json()["data"] if item["group_id"] == orange.group_id)
    assert row["price"] == 700.0


@pytest.mark.asyncio
async def test_assign_test_group_provider_mismatch_rejected(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=933, role="admin")
    group = DiagnosticProfileGroup()
    test_db_session.add(group)
    await test_db_session.flush()
    pkg_group = DiagnosticPackageGroup()
    test_db_session.add(pkg_group)
    await test_db_session.flush()
    package = DiagnosticPackage(
        package_group_id=pkg_group.package_group_id,
        is_default_for_group=True,
        package_name="Mismatch Pkg",
        diagnostic_provider="orange_health",
        status="active",
        package_for="public",
    )
    tg = DiagnosticTestGroup(
        profile_group_id=group.profile_group_id,
        is_default_for_group=True,
        group_name="Healthians TG",
        group_key="mismatch_tg_h",
        diagnostic_provider="healthians",
    )
    test_db_session.add_all([package, tg])
    await test_db_session.commit()
    await test_db_session.refresh(package)
    await test_db_session.refresh(tg)

    response = await async_client.post(
        f"/diagnostic-packages/{package.diagnostic_package_id}/test-groups",
        headers=employee_auth_header(933),
        json={"group_ids": [tg.group_id]},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "DIAGNOSTIC_TEST_GROUP_PROVIDER_MISMATCH"


@pytest.mark.asyncio
async def test_assign_null_provider_test_group_allowed_with_warning_on_package_list(
    async_client, test_db_session,
):
    await seed_employee(test_db_session, employee_id=934, role="admin")
    group = DiagnosticProfileGroup()
    test_db_session.add(group)
    await test_db_session.flush()
    pkg_group = DiagnosticPackageGroup()
    test_db_session.add(pkg_group)
    await test_db_session.flush()
    package = DiagnosticPackage(
        package_group_id=pkg_group.package_group_id,
        is_default_for_group=True,
        package_name="Null TG Pkg",
        diagnostic_provider="healthians",
        status="active",
        package_for="public",
    )
    tg = DiagnosticTestGroup(
        profile_group_id=group.profile_group_id,
        is_default_for_group=True,
        group_name="Null provider TG",
        group_key="null_provider_tg",
        diagnostic_provider=None,
    )
    test_db_session.add_all([package, tg])
    await test_db_session.commit()
    await test_db_session.refresh(package)
    await test_db_session.refresh(tg)

    assign = await async_client.post(
        f"/diagnostic-packages/{package.diagnostic_package_id}/test-groups",
        headers=employee_auth_header(934),
        json={"group_ids": [tg.group_id]},
    )
    assert assign.status_code in (200, 201)

    groups = await async_client.get(
        "/diagnostic-packages/groups",
        params={"include_inactive": True, "type": "public_package"},
        headers=employee_auth_header(934),
    )
    row = next(
        item for item in groups.json()["data"] if item["diagnostic_package_id"] == package.diagnostic_package_id
    )
    codes = {w["code"] for w in row.get("warnings", [])}
    assert "test_group_provider_missing" in codes
