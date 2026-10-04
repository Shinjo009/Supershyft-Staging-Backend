"""Tests for integration_sync_logs on Google Maps and Nominatim geocoding."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from core.config import settings
from db.column_types import STATUS_INTEGRATION_SYNC
from modules.geocoding.client import (
    GOOGLE_GEOCODE_URL,
    NOMINATIM_SEARCH_URL,
    search_google,
    search_nominatim,
    search_places_for_booking,
)
from modules.geocoding.enums import GeocodingProvider


class _MockHttpxResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class _MockHttpxClient:
    def __init__(self, *args, **kwargs):
        self._payload = kwargs.pop("_payload")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, **kwargs):
        return _MockHttpxResponse(self._payload)


@pytest.mark.asyncio
async def test_search_google_writes_sync_log_without_api_key_in_payload(
    test_db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", "secret-test-key")
    google_payload = {
        "status": "OK",
        "results": [
            {
                "formatted_address": "Mumbai, Maharashtra, India",
                "address_components": [
                    {"long_name": "Mumbai", "short_name": "Mumbai", "types": ["locality", "political"]},
                    {"long_name": "400053", "short_name": "400053", "types": ["postal_code"]},
                ],
                "geometry": {"location": {"lat": 19.0, "lng": 72.0}},
            }
        ],
    }

    def _client_factory(*args, **kwargs):
        return _MockHttpxClient(_payload=google_payload, **kwargs)

    monkeypatch.setattr("modules.geocoding.client.httpx.AsyncClient", _client_factory)

    results = await search_google("Mumbai 400053", limit=1)
    assert len(results) == 1

    row = (
        await test_db_session.execute(
            text(
                "SELECT provider, status, api_endpoint_url, request_payload, error_message "
                "FROM integration_sync_logs WHERE provider = 'google_maps' "
                "ORDER BY sync_log_id DESC LIMIT 1"
            )
        )
    ).one()
    assert row.status == STATUS_INTEGRATION_SYNC["success"]
    assert row.api_endpoint_url == GOOGLE_GEOCODE_URL
    assert row.request_payload.get("address") == "Mumbai 400053"
    assert "key" not in row.request_payload
    assert row.error_message is None


@pytest.mark.asyncio
async def test_search_google_missing_api_key_logs_failed_without_http(test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", "")

    async def _should_not_http(*args, **kwargs):
        raise AssertionError("HTTP should not be called when API key is missing")

    monkeypatch.setattr("modules.geocoding.client.httpx.AsyncClient", _should_not_http)

    results = await search_google("Mumbai", limit=1)
    assert results == []

    row = (
        await test_db_session.execute(
            text(
                "SELECT status, error_message FROM integration_sync_logs "
                "WHERE provider = 'google_maps' ORDER BY sync_log_id DESC LIMIT 1"
            )
        )
    ).one()
    assert row.status == STATUS_INTEGRATION_SYNC["failed"]
    assert "GOOGLE_MAPS_API_KEY" in (row.error_message or "")


@pytest.mark.asyncio
async def test_search_nominatim_writes_sync_log(test_db_session, monkeypatch):
    nominatim_payload = [
        {
            "display_name": "Mumbai, India",
            "lat": "19.0760",
            "lon": "72.8777",
            "address": {"city": "Mumbai", "postcode": "400001", "country": "India"},
        }
    ]

    def _client_factory(*args, **kwargs):
        return _MockHttpxClient(_payload=nominatim_payload, **kwargs)

    monkeypatch.setattr("modules.geocoding.client.httpx.AsyncClient", _client_factory)

    results = await search_nominatim("Mumbai 400001", limit=1)
    assert len(results) == 1

    row = (
        await test_db_session.execute(
            text(
                "SELECT provider, status, api_endpoint_url, request_payload "
                "FROM integration_sync_logs WHERE provider = 'nominatim' "
                "ORDER BY sync_log_id DESC LIMIT 1"
            )
        )
    ).one()
    assert row.status == STATUS_INTEGRATION_SYNC["success"]
    assert row.api_endpoint_url == NOMINATIM_SEARCH_URL
    assert row.request_payload.get("q") == "Mumbai 400001"


@pytest.mark.asyncio
async def test_search_places_for_booking_fallback_creates_two_sync_logs(test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", "secret-test-key")
    calls: list[str] = []

    async def _google(query: str, *, limit: int = 3, engagement_id=None, user_id=None):
        calls.append(f"google:{query}")
        return []

    async def _nominatim(query: str, *, limit: int = 3, engagement_id=None, user_id=None):
        calls.append(f"nominatim:{query}")
        return [{"latitude": 19.1, "longitude": 72.8, "city": "Mumbai", "pincode": "400053"}]

    monkeypatch.setattr("modules.geocoding.client.search_google", _google)
    monkeypatch.setattr("modules.geocoding.client.search_nominatim", _nominatim)

    await search_places_for_booking(
        address_line="C/401",
        landmark="Park",
        city="Mumbai",
        pincode="400053",
        primary=GeocodingProvider.google,
        user_id=99,
    )

    assert calls == [
        "google:C/401, Park, Mumbai, 400053",
        "nominatim:Mumbai 400053",
    ]
