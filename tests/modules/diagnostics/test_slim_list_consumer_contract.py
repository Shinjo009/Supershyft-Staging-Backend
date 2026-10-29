"""Contract checks: slim list responses still satisfy member app + admin list consumers."""

from __future__ import annotations

import pytest

from modules.diagnostics.models import DiagnosticPackage, DiagnosticPackageGroup
from tests.helpers.auth import employee_auth_header, seed_employee

MEMBER_LIST_REQUIRED_KEYS = {
    "diagnostic_package_id",
    "package_name",
    "price",
    "tags",
    "filter_chips",
    "gender_suitability",
    "discount_percent",
    "no_of_tests",
}

MEMBER_LIST_FORBIDDEN_KEYS = {
    "same_packages",
    "status",
    "package_for",
    "external_package_code",
    "unmapped_test_count",
    "is_default_for_group",
}

ADMIN_GROUPS_REQUIRED_KEYS = {
    "package_group",
    "has_unmapped_tests",
    "diagnostic_package_id",
    "diagnostic_provider",
}

DETAIL_REQUIRED_KEYS = {
    "same_packages",
    "status",
    "package_for",
    "external_package_code",
    "is_default_for_group",
    "tags",
    "filter_chips",
}


async def _add_default_package(session, **fields) -> DiagnosticPackage:
    group = DiagnosticPackageGroup()
    session.add(group)
    await session.flush()
    pkg = DiagnosticPackage(
        package_group_id=group.package_group_id,
        is_default_for_group=True,
        status="active",
        package_for="public",
        **fields,
    )
    session.add(pkg)
    await session.commit()
    await session.refresh(pkg)
    return pkg


@pytest.mark.asyncio
async def test_member_list_and_admin_groups_contract(async_client, test_db_session):
    await _add_default_package(
        test_db_session,
        package_name="Contract Pkg",
        diagnostic_provider="healthians",
        price=999,
    )

    list_resp = await async_client.get("/diagnostic-packages", params={"type": "public_package"})
    assert list_resp.status_code == 200
    rows = list_resp.json()["data"]
    assert rows
    sample = rows[0]
    assert MEMBER_LIST_REQUIRED_KEYS.issubset(sample.keys())
    assert MEMBER_LIST_FORBIDDEN_KEYS.isdisjoint(sample.keys())

    await seed_employee(test_db_session, employee_id=9901, role="admin")
    groups_resp = await async_client.get(
        "/diagnostic-packages/groups",
        params={"include_inactive": True, "type": "public_package"},
        headers=employee_auth_header(9901),
    )
    assert groups_resp.status_code == 200
    group_rows = groups_resp.json()["data"]
    assert group_rows
    group_sample = group_rows[0]
    assert ADMIN_GROUPS_REQUIRED_KEYS.issubset(group_sample.keys())
    assert "same_packages" not in group_sample
    assert "unmapped_test_count" not in group_sample

    pkg_id = sample["diagnostic_package_id"]
    detail_resp = await async_client.get(f"/diagnostic-packages/{pkg_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()["data"]
    assert DETAIL_REQUIRED_KEYS.issubset(detail.keys())


@pytest.mark.asyncio
async def test_bootstrap_diagnostic_picker_contract(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=9902, role="admin")
    resp = await async_client.get(
        "/engagements/form-bootstrap",
        headers=employee_auth_header(9902),
    )
    assert resp.status_code == 200
    packages = resp.json()["data"]["diagnostic_packages"]
    if not packages:
        pytest.skip("no diagnostic packages in bootstrap fixture")
    row = packages[0]
    assert "external_package_code" in row
    assert "complementary_consultation" in row
    assert "same_packages" not in row
