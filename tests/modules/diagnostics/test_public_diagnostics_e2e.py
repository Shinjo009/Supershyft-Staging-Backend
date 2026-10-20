"""E2E-style tests for public diagnostic routes (mocked providers)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from modules.diagnostics.models import DiagnosticPackage, DiagnosticPackageGroup


async def _add_package(session, *, provider: str, **fields) -> DiagnosticPackage:
    group = DiagnosticPackageGroup()
    session.add(group)
    await session.flush()
    defaults = {
        "package_name": "Public Test Pkg",
        "diagnostic_provider": provider,
        "external_package_code": "package_119",
        "status": "active",
        "package_for": "public",
        "original_price": 600,
    }
    defaults.update(fields)
    pkg = DiagnosticPackage(package_group_id=group.package_group_id, **defaults)
    session.add(pkg)
    await session.commit()
    await session.refresh(pkg)
    return pkg


@pytest.mark.asyncio
async def test_public_serviceability_healthians_no_engagement_rows(async_client, test_db_session):
    from modules.engagements.models import Engagement

    before = await test_db_session.execute(
        __import__("sqlalchemy").select(__import__("sqlalchemy").func.count()).select_from(Engagement)
    )
    count_before = int(before.scalar_one())

    mock_check = AsyncMock(return_value={"status": True, "message": "ok", "data": {"zone_id": "Z1"}})

    with patch(
        "modules.diagnostics.public_service._get_healthians_token",
        new_callable=AsyncMock,
        return_value="token",
    ), patch(
        "modules.diagnostics.public_service.healthians_client.check_serviceability_by_location_v2",
        mock_check,
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
    assert len(body["providers"]) == 1
    hi = body["providers"][0]
    assert hi["provider"] == "healthians"
    assert hi["serviceable"] is True
    assert hi["zone_id"] == "Z1"
    mock_check.assert_awaited_once()
    call_kwargs = mock_check.await_args.kwargs
    assert call_kwargs["lat"] == "28.6"
    assert call_kwargs["long"] == "77.2"

    after = await test_db_session.execute(
        __import__("sqlalchemy").select(__import__("sqlalchemy").func.count()).select_from(Engagement)
    )
    assert int(after.scalar_one()) == count_before


@pytest.mark.asyncio
async def test_public_serviceability_all_providers(async_client):
    with patch(
        "modules.diagnostics.public_service._get_healthians_token",
        new_callable=AsyncMock,
        return_value="token",
    ), patch(
        "modules.diagnostics.public_service.healthians_client.check_serviceability_by_location_v2",
        new_callable=AsyncMock,
        return_value={"status": True, "message": "hi ok", "data": {"zone_id": "Z1"}},
    ), patch(
        "modules.diagnostics.public_service.orange_health_flow.check_serviceability_at_location",
        new_callable=AsyncMock,
        return_value={"status": "success", "message": "oh ok"},
    ), patch(
        "modules.diagnostics.public_service.enrich_location_fields",
        new_callable=AsyncMock,
        return_value={"latitude": 28.6, "longitude": 77.2},
    ):
        response = await async_client.post(
            "/diagnostics/public/serviceability",
            json={
                "provider": None,
                "address_line": "Test address",
                "city": "Delhi",
                "pincode": "110001",
            },
        )

    assert response.status_code == 200
    providers = response.json()["data"]["providers"]
    assert len(providers) == 2
    assert {p["provider"] for p in providers} == {"healthians", "orange_health"}


@pytest.mark.asyncio
async def test_public_available_slots_requires_lat_long(async_client, test_db_session):
    pkg = await _add_package(test_db_session, provider="healthians")
    response = await async_client.post(
        "/diagnostics/public/available-slots",
        json={
            "provider": "healthians",
            "slot_date": "2026-04-15",
            "diagnostic_package_id": pkg.diagnostic_package_id,
            "zone_id": "440",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_public_available_slots_healthians_requires_zone_id(async_client, test_db_session):
    pkg = await _add_package(test_db_session, provider="healthians")
    response = await async_client.post(
        "/diagnostics/public/available-slots",
        json={
            "provider": "healthians",
            "slot_date": "2026-04-15",
            "diagnostic_package_id": pkg.diagnostic_package_id,
            "latitude": 28.4595,
            "longitude": 77.0266,
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_public_available_slots_provider_package_mismatch(async_client, test_db_session):
    pkg = await _add_package(test_db_session, provider="orange_health")
    response = await async_client.post(
        "/diagnostics/public/available-slots",
        json={
            "provider": "healthians",
            "slot_date": "2026-04-15",
            "diagnostic_package_id": pkg.diagnostic_package_id,
            "zone_id": "440",
            "latitude": 28.4595,
            "longitude": 77.0266,
        },
    )
    assert response.status_code == 422
    assert response.json().get("error_code") == "PROVIDER_PACKAGE_MISMATCH"


@pytest.mark.asyncio
async def test_public_available_slots_orange_without_package(async_client):
    with patch(
        "modules.diagnostics.public_service.orange_health_flow.fetch_slots_for_location",
        new_callable=AsyncMock,
        return_value={"status": "success", "slots": [{"stm_id": "1", "slot_time": "09:00"}]},
    ):
        response = await async_client.post(
            "/diagnostics/public/available-slots",
            json={
                "provider": "orange_health",
                "slot_date": "2026-04-15",
                "diagnostic_package_id": None,
                "latitude": 28.4595,
                "longitude": 77.0266,
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "orange_health"
    assert len(data["slots"]) == 1