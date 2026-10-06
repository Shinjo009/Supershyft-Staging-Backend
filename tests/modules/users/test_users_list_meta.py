"""Users list meta includes stats and protected_user_ids."""

from __future__ import annotations

import pytest

from tests.helpers.auth import employee_auth_header, seed_employee


@pytest.mark.asyncio
async def test_users_list_includes_meta_stats(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8802, role="admin")
    response = await async_client.get("/users", headers=employee_auth_header(8802), params={"limit": 5})
    assert response.status_code == 200
    meta = response.json()["meta"]
    assert "with_metsights_profile" in meta
    assert "total_participants" in meta
    assert "protected_user_ids" in meta
    assert isinstance(meta["protected_user_ids"], list)
    assert "yearly_totals" not in meta
