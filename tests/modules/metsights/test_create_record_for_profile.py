"""Tests for MetsightsService.create_record_for_profile fallback and error messages."""

from __future__ import annotations

import httpx
import pytest

from core.config import settings
from modules.metsights.client import MetsightsClient
from modules.metsights.service import MetsightsService

_SUB_PRO = "01975457-778f-064b-78a5-6990afec7881"
_PROFILE = "01961d4b-3cb1-cfae-f876-2957ef9acf18"
_EXISTING_RECORD = "08AB25490686"


def _http_status_error(status: int, body: str) -> httpx.HTTPStatusError:
    request = httpx.Request(
        "POST",
        f"https://api.metsights.com/external/profiles/{_PROFILE}/records/",
    )
    response = httpx.Response(status, text=body, request=request)
    return httpx.HTTPStatusError("error", request=request, response=response)


@pytest.mark.asyncio
async def test_create_record_reuses_existing_on_create_500(monkeypatch):
    monkeypatch.setattr(settings, "METSIGHTS_API_KEY", "test-key")
    service = MetsightsService(MetsightsClient())

    async def _create_profile_record(self, *, profile_id: str, data: dict):
        raise _http_status_error(500, '{"detail":"internal error"}')

    async def _list_profile_records(self, *, profile_id: str, **kwargs):
        assert profile_id == _PROFILE
        return {
            "data": [
                {
                    "id": _EXISTING_RECORD,
                    "subscription": {"id": _SUB_PRO},
                }
            ]
        }

    monkeypatch.setattr(
        "modules.metsights.client.MetsightsClient.create_profile_record",
        _create_profile_record,
    )
    monkeypatch.setattr(
        "modules.metsights.client.MetsightsClient.list_profile_records",
        _list_profile_records,
    )

    record_id = await service.create_record_for_profile(
        profile_id=_PROFILE,
        subscription_id=_SUB_PRO,
    )
    assert record_id == _EXISTING_RECORD


@pytest.mark.asyncio
async def test_create_record_surfaces_upstream_body_when_no_existing(monkeypatch):
    monkeypatch.setattr(settings, "METSIGHTS_API_KEY", "test-key")
    service = MetsightsService(MetsightsClient())

    async def _create_profile_record(self, *, profile_id: str, data: dict):
        raise _http_status_error(500, '{"detail":"duplicate subscription"}')

    async def _list_profile_records(self, *, profile_id: str, **kwargs):
        return {"data": []}

    monkeypatch.setattr(
        "modules.metsights.client.MetsightsClient.create_profile_record",
        _create_profile_record,
    )
    monkeypatch.setattr(
        "modules.metsights.client.MetsightsClient.list_profile_records",
        _list_profile_records,
    )

    from core.exceptions import AppError

    with pytest.raises(AppError) as exc_info:
        await service.create_record_for_profile(
            profile_id=_PROFILE,
            subscription_id=_SUB_PRO,
        )
    assert "HTTP 500" in exc_info.value.message
    assert "duplicate subscription" in exc_info.value.message
