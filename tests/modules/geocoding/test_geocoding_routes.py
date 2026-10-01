"""Route tests for GET /geocode/search meta and provider fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from modules.employee.models import Employee
from modules.geocoding.enums import GeocodingProvider
from modules.users.models import User
from tests.helpers.auth import employee_auth_header


_SAMPLE = [
    {
        "display_name": "Bengaluru, Karnataka 560001, India",
        "address": "Bengaluru, Karnataka 560001, India",
        "sub_locality": None,
        "landmark": None,
        "city": "Bengaluru",
        "pincode": "560001",
        "state": "Karnataka",
        "country": "India",
        "latitude": 12.9765944,
        "longitude": 77.5992708,
    }
]


@pytest.mark.asyncio
async def test_geocode_search_requires_auth(async_client):
    response = await async_client.get("/geocode/search", params={"q": "Bangalore 560001"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_geocode_search_returns_meta_without_fallback(async_client, test_db_session):
    uid = 9201
    test_db_session.add(User(user_id=uid, age=30, phone="92010000001", status="active"))
    await test_db_session.flush()
    test_db_session.add(
        Employee(
            employee_id=9201,
            name="Employee 9201",
            phone="0000009201",
            email="employee9201@test.example",
            role="admin",
            status="active",
        )
    )
    await test_db_session.commit()

    with patch(
        "modules.geocoding.router.search_places_with_fallback",
        new_callable=AsyncMock,
        return_value=(
            _SAMPLE,
            {"geocoding_provider": "google", "geocoding_fallback_used": False},
        ),
    ) as mock_search:
        response = await async_client.get(
            "/geocode/search",
            params={"q": "Bangalore 560001", "limit": 1},
            headers=employee_auth_header(uid),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == _SAMPLE
    assert body["meta"]["geocoding_provider"] == "google"
    assert body["meta"]["geocoding_fallback_used"] is False
    mock_search.assert_awaited_once()
    kwargs = mock_search.await_args.kwargs
    assert kwargs["limit"] == 1
    assert kwargs["primary"] == GeocodingProvider.google


@pytest.mark.asyncio
async def test_geocode_search_uses_configured_nominatim_primary(async_client, test_db_session):
    uid = 9202
    test_db_session.add(User(user_id=uid, age=30, phone="92020000001", status="active"))
    await test_db_session.flush()
    test_db_session.add(
        Employee(
            employee_id=9202,
            name="Employee 9202",
            phone="0000009202",
            email="employee9202@test.example",
            role="admin",
            status="active",
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, status) VALUES "
            "(1, 'P1', 'One', 1) "
            "ON CONFLICT (package_id) DO UPDATE SET status = EXCLUDED.status"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, reference_id, package_name, diagnostic_provider, status) "
            "VALUES (1, 'R1', 'D1', 'p', 1) "
            "ON CONFLICT (diagnostic_package_id) DO UPDATE SET status = EXCLUDED.status"
        )
    )
    await test_db_session.execute(text("DELETE FROM platform_settings"))
    await test_db_session.execute(
        text(
            "INSERT INTO platform_settings "
            "(settings_id, b2c_default_assessment_package_id, b2c_default_diagnostic_package_id, geocoding_provider) "
            "VALUES (1, 1, 1, 'nominatim')"
        )
    )
    await test_db_session.commit()

    with patch(
        "modules.geocoding.router.search_places_with_fallback",
        new_callable=AsyncMock,
        return_value=(
            _SAMPLE,
            {"geocoding_provider": "google", "geocoding_fallback_used": True},
        ),
    ) as mock_search:
        response = await async_client.get(
            "/geocode/search",
            params={"q": "Bangalore 560001", "limit": 1},
            headers=employee_auth_header(uid),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["geocoding_provider"] == "google"
    assert body["meta"]["geocoding_fallback_used"] is True
    assert mock_search.await_args.kwargs["primary"] == GeocodingProvider.nominatim
