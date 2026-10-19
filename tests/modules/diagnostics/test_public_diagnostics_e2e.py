"""E2E-style tests for public diagnostic routes (mocked providers)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_public_serviceability_healthians_no_engagement_rows(async_client, test_db_session):
    from modules.engagements.models import Engagement

    before = await test_db_session.execute(
        __import__("sqlalchemy").select(__import__("sqlalchemy").func.count()).select_from(Engagement)
    )
    count_before = int(before.scalar_one())

    with patch(
        "modules.diagnostics.public_service._get_healthians_token",
        new_callable=AsyncMock,
        return_value="token",
    ), patch(
        "modules.diagnostics.public_service.healthians_client.check_serviceability_by_location_v2",
        new_callable=AsyncMock,
        return_value={"status": True, "message": "ok", "data": {"zone_id": "Z1"}},
    ), patch(
        "modules.diagnostics.public_service.enrich_location_fields",
        new_callable=AsyncMock,
        return_value={"latitude": 28.6, "longitude": 77.2, "city": "Delhi"},
    ):
        response = await async_client.post(
            "/diagnostics/public/serviceability",
            json={
                "provider": "healthians",
                "address_line": "Test address",
                "city": "Delhi",
                "pincode": "110001",
            },
        )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["serviceable"] is True
    assert body["zone_id"] == "Z1"

    after = await test_db_session.execute(
        __import__("sqlalchemy").select(__import__("sqlalchemy").func.count()).select_from(Engagement)
    )
    assert int(after.scalar_one()) == count_before


@pytest.mark.asyncio
async def test_public_lock_slot_orange_noop(async_client):
    response = await async_client.post(
        "/diagnostics/public/lock-slot",
        json={
            "provider": "orange_health",
            "slot_id": "slot-1",
            "slot_date": "2026-12-01",
            "slot_time": "09:00",
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["locked"] is False
