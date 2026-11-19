"""Tests for BioAI report generation guard on MetsightsService."""

from __future__ import annotations

import httpx
import pytest
from unittest.mock import MagicMock

from core.config import settings
from core.exceptions import AppError
from modules.metsights.client import MetsightsClient
from modules.metsights.service import MetsightsService


@pytest.mark.asyncio
async def test_is_bioai_report_generated_true_when_has_report(monkeypatch):
    monkeypatch.setattr(settings, "METSIGHTS_API_KEY", "test-key")

    get_report_calls = 0

    async def _get_report(self, *, record_id: str, assessment_type_code: str | None):
        nonlocal get_report_calls
        get_report_calls += 1
        return {"detail": "ok", "data": {"id": record_id}}

    async def _detail(self, *, record_id: str):
        return {"detail": "ok", "data": {"id": record_id, "has_report": True}}

    monkeypatch.setattr(MetsightsClient, "get_report", _get_report)
    monkeypatch.setattr(MetsightsClient, "get_record_detail", _detail)
    svc = MetsightsService(client=MetsightsClient())
    assert await svc.is_bioai_report_generated(record_id="ABC123", assessment_type_code="1") is True
    assert get_report_calls == 0


@pytest.mark.asyncio
async def test_is_bioai_report_generated_false_when_has_report_false(monkeypatch):
    monkeypatch.setattr(settings, "METSIGHTS_API_KEY", "test-key")

    async def _detail(self, *, record_id: str):
        return {"detail": "ok", "data": {"id": record_id, "has_report": False}}

    monkeypatch.setattr(MetsightsClient, "get_record_detail", _detail)
    svc = MetsightsService(client=MetsightsClient())
    assert await svc.is_bioai_report_generated(record_id="ABC123", assessment_type_code="2") is False


@pytest.mark.asyncio
async def test_is_bioai_report_generated_returns_false_on_record_404(monkeypatch):
    monkeypatch.setattr(settings, "METSIGHTS_API_KEY", "test-key")

    async def _detail(self, *, record_id: str):
        response = MagicMock()
        response.status_code = 404
        raise httpx.HTTPStatusError("not found", request=MagicMock(), response=response)

    monkeypatch.setattr(MetsightsClient, "get_record_detail", _detail)
    svc = MetsightsService(client=MetsightsClient())
    assert await svc.is_bioai_report_generated(record_id="ABC123", assessment_type_code="1") is False


@pytest.mark.asyncio
async def test_is_bioai_report_generated_raises_on_403(monkeypatch):
    monkeypatch.setattr(settings, "METSIGHTS_API_KEY", "test-key")

    async def _detail(self, *, record_id: str):
        response = MagicMock()
        response.status_code = 403
        raise httpx.HTTPStatusError("forbidden", request=MagicMock(), response=response)

    monkeypatch.setattr(MetsightsClient, "get_record_detail", _detail)
    svc = MetsightsService(client=MetsightsClient())

    with pytest.raises(AppError) as exc_info:
        await svc.is_bioai_report_generated(record_id="ABC123", assessment_type_code="1")
    assert exc_info.value.error_code == "EXTERNAL_SERVICE_UNAVAILABLE"