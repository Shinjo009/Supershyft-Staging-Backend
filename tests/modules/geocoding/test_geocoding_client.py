"""Unit tests for Nominatim/Google mapping, fallback, and location enrichment."""

from __future__ import annotations

import pytest

from modules.geocoding.client import (
    build_booking_geocode_queries,
    enrich_location_fields,
    location_fields_complete,
    map_google_result,
    map_nominatim_result,
    merge_location_fields,
    search_places_for_booking,
    search_places_with_fallback,
)
from modules.geocoding.enums import GeocodingProvider


def test_map_nominatim_result_maps_expected_fields():
    mapped = map_nominatim_result(
        {
            "name": "Marol Naka (Line 1)",
            "display_name": "Marol Naka (Line 1), Mumbai, Maharashtra, 400072, India",
            "lat": "19.1083663",
            "lon": "72.8788727",
            "address": {
                "suburb": "Saki Naka",
                "neighbourhood": "Chimatpada",
                "city": "Mumbai",
                "state": "Maharashtra",
                "postcode": "400072",
                "country": "India",
            },
        }
    )
    assert mapped["landmark"] == "Marol Naka (Line 1)"
    assert mapped["sub_locality"] == "Saki Naka"
    assert mapped["city"] == "Mumbai"
    assert mapped["pincode"] == "400072"
    assert mapped["state"] == "Maharashtra"
    assert mapped["country"] == "India"
    assert mapped["latitude"] == pytest.approx(19.1083663)
    assert mapped["longitude"] == pytest.approx(72.8788727)


def test_map_google_result_maps_expected_fields():
    mapped = map_google_result(
        {
            "formatted_address": "Bengaluru, Karnataka 560001, India",
            "address_components": [
                {"long_name": "Bengaluru", "short_name": "Bengaluru", "types": ["locality", "political"]},
                {"long_name": "Karnataka", "short_name": "KA", "types": ["administrative_area_level_1", "political"]},
                {"long_name": "560001", "short_name": "560001", "types": ["postal_code"]},
                {"long_name": "India", "short_name": "IN", "types": ["country", "political"]},
            ],
            "geometry": {"location": {"lat": 12.9765944, "lng": 77.5992708}},
        }
    )
    assert mapped["display_name"] == "Bengaluru, Karnataka 560001, India"
    assert mapped["address"] == "Bengaluru, Karnataka 560001, India"
    assert mapped["city"] == "Bengaluru"
    assert mapped["pincode"] == "560001"
    assert mapped["state"] == "Karnataka"
    assert mapped["country"] == "India"
    assert mapped["latitude"] == pytest.approx(12.9765944)
    assert mapped["longitude"] == pytest.approx(77.5992708)


def test_build_booking_geocode_queries_google_vs_nominatim():
    google_q, nominatim_q = build_booking_geocode_queries(
        address_line="C/401, Sundar nagar",
        landmark="Veera Desai Road",
        city="Mumbai",
        pincode="400053",
    )
    assert google_q == "C/401, Sundar nagar, Veera Desai Road, Mumbai, 400053"
    assert nominatim_q == "Mumbai 400053"


@pytest.mark.asyncio
async def test_search_places_for_booking_google_primary_uses_full_address_on_fallback_nominatim(
    monkeypatch,
):
    calls: list[tuple[str, str]] = []

    async def _google(query: str, *, limit: int = 3, **kwargs):
        calls.append(("google", query))
        return []

    async def _nominatim(query: str, *, limit: int = 3, **kwargs):
        calls.append(("nominatim", query))
        return [{"latitude": 19.1, "longitude": 72.8}]

    monkeypatch.setattr("modules.geocoding.client.search_google", _google)
    monkeypatch.setattr("modules.geocoding.client.search_nominatim", _nominatim)

    results = await search_places_for_booking(
        address_line="C/401",
        landmark="Park",
        city="Mumbai",
        pincode="400053",
        primary=GeocodingProvider.google,
    )
    assert len(results) == 1
    assert calls == [
        ("google", "C/401, Park, Mumbai, 400053"),
        ("nominatim", "Mumbai 400053"),
    ]


@pytest.mark.asyncio
async def test_search_places_for_booking_nominatim_primary_uses_city_pincode(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def _google(query: str, *, limit: int = 3, **kwargs):
        calls.append(("google", query))
        return [{"latitude": 19.1, "longitude": 72.8}]

    async def _nominatim(query: str, *, limit: int = 3, **kwargs):
        calls.append(("nominatim", query))
        return []

    monkeypatch.setattr("modules.geocoding.client.search_google", _google)
    monkeypatch.setattr("modules.geocoding.client.search_nominatim", _nominatim)

    await search_places_for_booking(
        address_line="C/401",
        landmark="Park",
        city="Mumbai",
        pincode="400053",
        primary=GeocodingProvider.nominatim,
    )
    assert calls[0] == ("nominatim", "Mumbai 400053")
    assert calls[1] == ("google", "C/401, Park, Mumbai, 400053")


def test_map_google_result_street_level_address_line_and_landmark():
    mapped = map_google_result(
        {
            "formatted_address": "123 MG Road, Saki Naka, Mumbai, Maharashtra 400072, India",
            "address_components": [
                {"long_name": "123", "short_name": "123", "types": ["street_number"]},
                {"long_name": "MG Road", "short_name": "MG Rd", "types": ["route"]},
                {
                    "long_name": "Phoenix Marketcity",
                    "short_name": "Phoenix Marketcity",
                    "types": ["point_of_interest", "establishment"],
                },
                {"long_name": "Saki Naka", "short_name": "Saki Naka", "types": ["sublocality_level_1", "political"]},
                {"long_name": "Mumbai", "short_name": "Mumbai", "types": ["locality", "political"]},
                {"long_name": "Maharashtra", "short_name": "MH", "types": ["administrative_area_level_1", "political"]},
                {"long_name": "400072", "short_name": "400072", "types": ["postal_code"]},
                {"long_name": "India", "short_name": "IN", "types": ["country", "political"]},
            ],
            "geometry": {"location": {"lat": 19.1083663, "lng": 72.8788727}},
        }
    )
    assert mapped["display_name"] == "123 MG Road, Saki Naka, Mumbai, Maharashtra 400072, India"
    assert mapped["address"] == "123 MG Road"
    assert mapped["sub_locality"] == "Saki Naka"
    assert mapped["landmark"] == "Phoenix Marketcity"
    assert mapped["city"] == "Mumbai"
    assert mapped["pincode"] == "400072"


def test_location_fields_complete_requires_all_fields():
    assert not location_fields_complete(address="A", city="Mumbai")
    assert location_fields_complete(
        address="A",
        sub_locality="S",
        landmark="L",
        city="Mumbai",
        pincode="400072",
        state="MH",
        country="India",
        latitude=19.1,
        longitude=72.8,
    )


def test_merge_location_fields_does_not_overwrite_existing():
    merged = merge_location_fields(
        {"address": "User Address", "city": None, "latitude": None},
        {"address": "Display Name", "city": "Mumbai", "latitude": 19.1},
    )
    assert merged["address"] == "User Address"
    assert merged["city"] == "Mumbai"
    assert merged["latitude"] == 19.1


@pytest.mark.asyncio
async def test_enrich_location_fields_skips_geocode_when_complete(monkeypatch):
    async def _should_not_run(*_args, **_kwargs):
        raise AssertionError("search_places should not be called")

    monkeypatch.setattr("modules.geocoding.client.search_places", _should_not_run)
    result = await enrich_location_fields(
        address="A",
        sub_locality="S",
        landmark="L",
        city="Mumbai",
        pincode="400072",
        state="MH",
        country="India",
        latitude=19.1,
        longitude=72.8,
    )
    assert result["city"] == "Mumbai"
    assert result["latitude"] == pytest.approx(19.1)


@pytest.mark.asyncio
async def test_enrich_location_fields_fills_missing_from_geocode(monkeypatch):
    async def _fake_search(query: str, *, limit: int = 3, primary=GeocodingProvider.google, **kwargs):
        assert "Marol" in query
        assert limit == 1
        assert primary == GeocodingProvider.google
        return [
            {
                "display_name": "Marol Naka, Mumbai",
                "address": "Marol Naka, Mumbai",
                "sub_locality": "Saki Naka",
                "landmark": "Marol Naka",
                "city": "Mumbai",
                "pincode": "400072",
                "state": "Maharashtra",
                "country": "India",
                "latitude": 19.1,
                "longitude": 72.8,
            }
        ]

    monkeypatch.setattr("modules.geocoding.client.search_places", _fake_search)
    result = await enrich_location_fields(address="Marol Naka", city="Mumbai")
    assert result["address"] == "Marol Naka"
    assert result["sub_locality"] == "Saki Naka"
    assert result["landmark"] == "Marol Naka"
    assert result["pincode"] == "400072"
    assert result["latitude"] == pytest.approx(19.1)


_SAMPLE_PLACE = {
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


@pytest.mark.asyncio
async def test_fallback_primary_success_no_fallback(monkeypatch):
    async def _google(*_a, **_k):
        return [_SAMPLE_PLACE]

    async def _nominatim(*_a, **_k):
        raise AssertionError("Nominatim should not be called")

    monkeypatch.setattr("modules.geocoding.client.search_google", _google)
    monkeypatch.setattr("modules.geocoding.client.search_nominatim", _nominatim)

    results, meta = await search_places_with_fallback("Bangalore 560001", primary=GeocodingProvider.google)
    assert len(results) == 1
    assert meta == {"geocoding_provider": "google", "geocoding_fallback_used": False}


@pytest.mark.asyncio
async def test_fallback_primary_empty_uses_secondary(monkeypatch):
    async def _google(*_a, **_k):
        return []

    async def _nominatim(*_a, **_k):
        return [_SAMPLE_PLACE]

    monkeypatch.setattr("modules.geocoding.client.search_google", _google)
    monkeypatch.setattr("modules.geocoding.client.search_nominatim", _nominatim)

    results, meta = await search_places_with_fallback("Bangalore 560001", primary=GeocodingProvider.google)
    assert len(results) == 1
    assert meta == {"geocoding_provider": "nominatim", "geocoding_fallback_used": True}


@pytest.mark.asyncio
async def test_fallback_nominatim_primary_falls_back_to_google(monkeypatch):
    async def _google(*_a, **_k):
        return [_SAMPLE_PLACE]

    async def _nominatim(*_a, **_k):
        return []

    monkeypatch.setattr("modules.geocoding.client.search_google", _google)
    monkeypatch.setattr("modules.geocoding.client.search_nominatim", _nominatim)

    results, meta = await search_places_with_fallback("Bangalore 560001", primary=GeocodingProvider.nominatim)
    assert len(results) == 1
    assert meta == {"geocoding_provider": "google", "geocoding_fallback_used": True}


@pytest.mark.asyncio
async def test_fallback_both_empty(monkeypatch):
    async def _empty(*_a, **_k):
        return []

    monkeypatch.setattr("modules.geocoding.client.search_google", _empty)
    monkeypatch.setattr("modules.geocoding.client.search_nominatim", _empty)

    results, meta = await search_places_with_fallback("nowhere", primary=GeocodingProvider.google)
    assert results == []
    assert meta == {"geocoding_provider": "google", "geocoding_fallback_used": True}
