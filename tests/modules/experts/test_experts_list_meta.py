"""Experts list meta includes expert_types."""

from __future__ import annotations

import pytest

from tests.helpers.auth import employee_auth_header, seed_employee


@pytest.mark.asyncio
async def test_experts_list_meta_types(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8805, role="admin")
    response = await async_client.get("/experts", headers=employee_auth_header(8805), params={"limit": 5})
    assert response.status_code == 200
    meta = response.json()["meta"]
    assert "expert_types" in meta
    assert isinstance(meta["expert_types"], list)
