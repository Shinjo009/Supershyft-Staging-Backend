"""Tests for forking diagnostic test groups for a single package."""

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


async def _package_with_group(session, *, group_key: str) -> tuple[DiagnosticPackage, DiagnosticTestGroup]:
    pkg_group = DiagnosticPackageGroup()
    session.add(pkg_group)
    await session.flush()
    pkg = DiagnosticPackage(
        package_group_id=pkg_group.package_group_id,
        package_name="Pkg A",
        status="active",
        package_for="public",
    )
    group = DiagnosticTestGroup(group_name="Liver Profile", group_key=group_key)
    test = HealthParameter(test_name="Albumin", parameter_type="test")
    session.add_all([pkg, group, test])
    await session.flush()
    session.add(
        DiagnosticPackageTestGroup(
            diagnostic_package_id=pkg.diagnostic_package_id,
            group_id=group.group_id,
            display_order=1,
        )
    )
    session.add(
        DiagnosticTestGroupTest(group_id=group.group_id, test_id=test.test_id, display_order=1)
    )
    await session.commit()
    await session.refresh(pkg)
    await session.refresh(group)
    return pkg, group


@pytest.mark.asyncio
async def test_fork_creates_copy_and_swaps_assignment(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=1101, role="admin")
    pkg, group = await _package_with_group(test_db_session, group_key="fork_test_liver_a")

    response = await async_client.post(
        f"/diagnostic-packages/{pkg.diagnostic_package_id}/test-groups/{group.group_id}/fork-for-package",
        headers=employee_auth_header(1101),
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["forked"] is True
    new_group_id = body["group_id"]
    assert new_group_id != group.group_id

    tests_res = await async_client.get(
        f"/diagnostic-packages/{pkg.diagnostic_package_id}/tests",
        headers=employee_auth_header(1101),
    )
    groups = tests_res.json()["data"]["groups"]
    assert len(groups) == 1
    assert groups[0]["group_id"] == new_group_id
    assert len(groups[0]["tests"]) == 1
    assert groups[0]["tests"][0]["test_name"] == "Albumin"

    original = await test_db_session.get(DiagnosticTestGroup, group.group_id)
    assert original is not None
    forked = await test_db_session.get(DiagnosticTestGroup, new_group_id)
    assert forked is not None
    assert forked.forked_from_group_id == group.group_id


@pytest.mark.asyncio
async def test_fork_copies_screening_flags(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=1104, role="admin")
    pkg, group = await _package_with_group(test_db_session, group_key="fork_test_screening")
    group.has_allergy_screening = True
    group.has_cancer_screening = True
    test_db_session.add(group)
    await test_db_session.commit()

    response = await async_client.post(
        f"/diagnostic-packages/{pkg.diagnostic_package_id}/test-groups/{group.group_id}/fork-for-package",
        headers=employee_auth_header(1104),
    )
    assert response.status_code == 200
    new_group_id = response.json()["data"]["group_id"]

    forked = await test_db_session.get(DiagnosticTestGroup, new_group_id)
    assert forked is not None
    assert forked.has_allergy_screening is True
    assert forked.has_cancer_screening is True


@pytest.mark.asyncio
async def test_fork_is_idempotent(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=1102, role="admin")
    pkg, group = await _package_with_group(test_db_session, group_key="fork_test_liver_b")

    first = await async_client.post(
        f"/diagnostic-packages/{pkg.diagnostic_package_id}/test-groups/{group.group_id}/fork-for-package",
        headers=employee_auth_header(1102),
    )
    assert first.status_code == 200
    forked_id = first.json()["data"]["group_id"]

    second = await async_client.post(
        f"/diagnostic-packages/{pkg.diagnostic_package_id}/test-groups/{forked_id}/fork-for-package",
        headers=employee_auth_header(1102),
    )
    assert second.status_code == 200
    assert second.json()["data"]["group_id"] == forked_id
    assert second.json()["data"]["forked"] is False


@pytest.mark.asyncio
async def test_other_package_still_uses_catalog_group(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=1103, role="admin")
    pkg_a, group = await _package_with_group(test_db_session, group_key="fork_test_liver_c")

    pkg_group_b = DiagnosticPackageGroup()
    test_db_session.add(pkg_group_b)
    await test_db_session.flush()
    pkg_b = DiagnosticPackage(
        package_group_id=pkg_group_b.package_group_id,
        package_name="Pkg B",
        status="active",
        package_for="public",
    )
    test_db_session.add(pkg_b)
    await test_db_session.flush()
    test_db_session.add(
        DiagnosticPackageTestGroup(
            diagnostic_package_id=pkg_b.diagnostic_package_id,
            group_id=group.group_id,
            display_order=1,
        )
    )
    await test_db_session.commit()

    fork = await async_client.post(
        f"/diagnostic-packages/{pkg_a.diagnostic_package_id}/test-groups/{group.group_id}/fork-for-package",
        headers=employee_auth_header(1103),
    )
    assert fork.status_code == 200

    tests_b = await async_client.get(f"/diagnostic-packages/{pkg_b.diagnostic_package_id}/tests")
    assert tests_b.json()["data"]["groups"][0]["group_id"] == group.group_id
