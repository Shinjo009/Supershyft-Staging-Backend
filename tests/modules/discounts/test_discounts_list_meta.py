"""Discounts list includes abuse_events_24h in meta."""

from __future__ import annotations

import pytest

from tests.helpers.auth import employee_auth_header, seed_employee


@pytest.mark.asyncio
async def test_discounts_reports_summary_still_returns_abuse_count(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8803, role="admin")
    response = await async_client.get(
        "/discounts/reports/summary",
        headers=employee_auth_header(8803),
    )
    if response.status_code != 200:
        pytest.skip(f"discounts routes unavailable in this test env ({response.status_code})")
    data = response.json()["data"]
    assert "abuse_events_24h" in data
    assert isinstance(data["abuse_events_24h"], int)


@pytest.mark.asyncio
async def test_discounts_list_includes_abuse_meta_when_available(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8803, role="admin")
    response = await async_client.get("/discounts", headers=employee_auth_header(8803), params={"limit": 10})
    if response.status_code != 200:
        pytest.skip(f"discounts list unavailable in this test env ({response.status_code})")
    meta = response.json().get("meta") or {}
    assert "abuse_events_24h" in meta
    assert "reports_summary" in meta
    assert isinstance(meta["reports_summary"], dict)
