"""Tests for Redcliffe area search coordinate resolution."""

from __future__ import annotations

import pytest

from modules.diagnostics.redcliffe.booking_helpers import build_redcliffe_place_query
from modules.diagnostics.redcliffe import service as redcliffe_service


def test_build_redcliffe_place_query_joins_parts():
    q = build_redcliffe_place_query(
        address_line="Flat 1, Block C",
        landmark="Near mall",
        city="Mumbai",
        pincode="400069",
    )
    assert "Flat 1" in q
    assert "400069" in q


@pytest.mark.asyncio
async def test_resolve_coordinates_for_booking_success(monkeypatch):
    async def fake_search(*, place_query: str):
        return {"results": [{"eloc": "P3I97P", "address": {"city": "Mumbai", "state": "Maharashtra", "pincode": "400069"}}]}

    async def fake_coords(*, eloc: str):
        return {"latitude": 19.07, "longitude": 72.87}

    monkeypatch.setattr(redcliffe_service.redcliffe_client, "search_area", fake_search)
    monkeypatch.setattr(redcliffe_service.redcliffe_client, "get_coordinates", fake_coords)

    geocoded = await redcliffe_service.resolve_coordinates_for_booking(
        None,
        address_line="Mumbai address",
        landmark=None,
        city="Mumbai",
        pincode="400069",
    )
    assert geocoded["latitude"] == pytest.approx(19.07)
    assert geocoded["geocoding_provider"] == "redcliffe"


@pytest.mark.asyncio
async def test_resolve_coordinates_uses_fallback_when_no_results(monkeypatch):
    async def fake_search(*, place_query: str):
        return {"results": []}

    monkeypatch.setattr(redcliffe_service.redcliffe_client, "search_area", fake_search)

    async def fallback():
        return {"latitude": 1.0, "longitude": 2.0, "city": "X"}

    geocoded = await redcliffe_service.resolve_coordinates_for_booking(
        None,
        address_line="nowhere",
        landmark=None,
        city="X",
        pincode="111111",
        fallback_geocode=fallback,
    )
    assert geocoded["latitude"] == 1.0