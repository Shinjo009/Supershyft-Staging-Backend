"""BioAI load requires archived diagnostic blood report before generation."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.config import settings
from modules.metsights.client import MetsightsClient
from modules.metsights.service import MetsightsService
from modules.notifications.load_bioai_reports import load_bioai_reports
from modules.notifications.repository import NotificationsRepository
from modules.notifications.service import NotificationsService
from tests.helpers.archived_blood_report import seed_archived_diagnostic_blood_report
from tests.modules.notifications.test_load_cron_sync_logs import _seed_bioai_participant


@pytest.mark.asyncio
async def test_load_bioai_reports_skips_without_archived_blood_pdf(test_db_session, monkeypatch):
    await _seed_bioai_participant(
        test_db_session,
        bioai_notification=None,
        seed_archived_blood=False,
    )
    monkeypatch.setattr(settings, "METSIGHTS_API_KEY", "test-key")
    metsights_service = MetsightsService(client=MetsightsClient())

    async def _fake_blood_params(*, record_id: str):
        return {"is_complete": True}

    async def _fake_report(*, record_id: str, assessment_type_code: str | None):
        return {"file": "https://example.com/bioai.pdf", "record_id": record_id}

    monkeypatch.setattr(metsights_service, "get_blood_parameters", _fake_blood_params)
    monkeypatch.setattr(metsights_service, "get_report", _fake_report)
    monkeypatch.setattr(
        "modules.notifications.load_bioai_reports.register_permanent_bio_ai_report_url",
        AsyncMock(return_value="https://bio-ai-reports.supershyft.com/r/gate-test"),
    )

    result = await load_bioai_reports(
        test_db_session,
        metsights_service=metsights_service,
        notifications_service=NotificationsService(NotificationsRepository()),
    )

    assert result["loaded"] == 0
    assert result["skipped"] >= 1
    assert any(
        d.get("reason") == "diagnostic blood report not available yet"
        for d in result["details"]
    )


@pytest.mark.asyncio
async def test_load_bioai_reports_loads_when_archived_blood_pdf_present(
    test_db_session, monkeypatch
):
    await _seed_bioai_participant(
        test_db_session,
        bioai_notification=None,
        seed_archived_blood=False,
    )
    await seed_archived_diagnostic_blood_report(
        test_db_session,
        user_id=99001,
        engagement_id=99001,
    )
    monkeypatch.setattr(settings, "METSIGHTS_API_KEY", "test-key")
    monkeypatch.setattr(settings, "BLOOD_REPORTS_BASE_URL", "https://supershyft.com/reports")
    metsights_service = MetsightsService(client=MetsightsClient())

    async def _fake_blood_params(*, record_id: str):
        return {"is_complete": True}

    async def _fake_report(*, record_id: str, assessment_type_code: str | None):
        return {"file": "https://example.com/bioai.pdf", "record_id": record_id}

    monkeypatch.setattr(metsights_service, "get_blood_parameters", _fake_blood_params)
    monkeypatch.setattr(metsights_service, "get_report", _fake_report)
    monkeypatch.setattr(
        "modules.notifications.load_bioai_reports.register_permanent_bio_ai_report_url",
        AsyncMock(return_value="https://bio-ai-reports.supershyft.com/r/gate-test"),
    )

    result = await load_bioai_reports(
        test_db_session,
        metsights_service=metsights_service,
        notifications_service=NotificationsService(NotificationsRepository()),
    )

    assert result["loaded"] == 1
