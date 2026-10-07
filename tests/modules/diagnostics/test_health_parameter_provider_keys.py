"""API tests for provider-specific health parameter keys."""

from __future__ import annotations

import pytest

from modules.diagnostics.models import HealthParameter
from tests.helpers.auth import employee_auth_header, seed_employee


@pytest.mark.asyncio
async def test_update_health_parameter_provider_keys(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=902, role="admin")
    row = HealthParameter(test_name="Albumin", parameter_type="test", is_available=True)
    test_db_session.add(row)
    await test_db_session.commit()
    await test_db_session.refresh(row)

    response = await async_client.put(
        f"/diagnostics/health-parameters/{row.test_id}",
        headers=employee_auth_header(902),
        json={
            "healthians_parameter_key": "135",
            "orangehealth_parameter_key": "oh-albumin",
        },
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["healthians_parameter_key"] == "135"
    assert body["orangehealth_parameter_key"] == "oh-albumin"
    assert "external_parameter_code" not in body


@pytest.mark.asyncio
async def test_get_health_parameter_exposes_provider_keys(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=903, role="admin")
    row = HealthParameter(
        test_name="GGPT",
        parameter_type="test",
        is_available=True,
        healthians_parameter_key="21",
    )
    test_db_session.add(row)
    await test_db_session.commit()
    await test_db_session.refresh(row)

    response = await async_client.get(
        f"/diagnostics/health-parameters/{row.test_id}",
        headers=employee_auth_header(903),
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["healthians_parameter_key"] == "21"
    assert body.get("orangehealth_parameter_key") in (None, "")
