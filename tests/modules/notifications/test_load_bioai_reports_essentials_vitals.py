"""BioAI load: MetSights Essentials skips forced vitals BP recovery."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from core.config import settings
from modules.assessments.dependencies import get_assessments_service
from modules.engagements.dependencies import get_engagements_service
from modules.metsights.client import MetsightsClient
from modules.metsights.service import MetsightsService
from modules.metsights.sync_service import MetsightsSyncService
from modules.notifications.load_bioai_reports import load_bioai_reports
from modules.notifications.repository import NotificationsRepository
from modules.notifications.service import NotificationsService
from modules.platform_settings.dependencies import get_platform_settings_service_readonly
from modules.questionnaire.repository import QuestionnaireRepository
from modules.users.repository import UsersRepository
from tests.modules.notifications.test_load_bioai_reports_vitals_fallback import (
    _build_sync_service,
    _seed_bioai_participant,
)


async def _seed_essentials_package(test_db_session) -> None:
    await test_db_session.execute(
        text(
            "UPDATE assessment_packages SET package_code = 'METSIGHTS_BASIC', "
            "display_name = 'MetSights Essentials', assessment_type_code = '1' "
            "WHERE package_id = 1"
        )
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_load_essentials_skips_vitals_bp_recovery(test_db_session, monkeypatch):
    await _seed_bioai_participant(
        test_db_session,
        user_id=199301,
        engagement_id=199301,
        assessment_id=199301,
    )
    await _seed_essentials_package(test_db_session)

    monkeypatch.setattr(settings, "METSIGHTS_API_KEY", "test-key")
    metsights_service = MetsightsService(client=MetsightsClient())
    assessments_service = get_assessments_service()
    sync_service = _build_sync_service(metsights_service)

    async def _fake_blood_params(*, record_id: str):
        return {"is_complete": True}

    async def _fake_report(*, record_id: str, assessment_type_code: str | None):
        return None

    push_mock = AsyncMock()
    draft_mock = AsyncMock(
        return_value={"responses_drafted": 2, "fallback_keys": ["systolic_blood_pressure"]}
    )
    monkeypatch.setattr(metsights_service, "get_blood_parameters", _fake_blood_params)
    monkeypatch.setattr(metsights_service, "get_report", _fake_report)
    monkeypatch.setattr(
        "modules.notifications.load_bioai_reports.register_permanent_bio_ai_report_url",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(sync_service, "_push_category_to_metsights", push_mock)
    monkeypatch.setattr(
        assessments_service,
        "draft_vitals_blood_pressure_fallbacks",
        draft_mock,
    )

    result = await load_bioai_reports(
        test_db_session,
        metsights_service=metsights_service,
        notifications_service=NotificationsService(NotificationsRepository()),
        assessments_service=assessments_service,
        sync_service=sync_service,
        send_notifications=False,
        user_ids={199301},
    )

    assert result["skipped"] == 1
    push_mock.assert_not_called()
    draft_mock.assert_not_called()


@pytest.mark.asyncio
async def test_load_essentials_loads_without_vitals_when_report_ready(
    test_db_session,
    monkeypatch,
):
    await _seed_bioai_participant(
        test_db_session,
        user_id=199302,
        engagement_id=199302,
        assessment_id=199302,
    )
    await _seed_essentials_package(test_db_session)

    monkeypatch.setattr(settings, "METSIGHTS_API_KEY", "test-key")
    metsights_service = MetsightsService(client=MetsightsClient())
    assessments_service = get_assessments_service()
    sync_service = _build_sync_service(metsights_service)

    async def _fake_blood_params(*, record_id: str):
        return {"is_complete": True}

    async def _fake_report(*, record_id: str, assessment_type_code: str | None):
        return {"file": "https://example.com/essentials-bioai.pdf", "record_id": record_id}

    push_mock = AsyncMock()
    monkeypatch.setattr(metsights_service, "get_blood_parameters", _fake_blood_params)
    monkeypatch.setattr(metsights_service, "get_report", _fake_report)
    monkeypatch.setattr(
        "modules.notifications.load_bioai_reports.register_permanent_bio_ai_report_url",
        AsyncMock(return_value="https://bio-ai-reports.supershyft.com/r/essentials"),
    )
    monkeypatch.setattr(sync_service, "_push_category_to_metsights", push_mock)

    result = await load_bioai_reports(
        test_db_session,
        metsights_service=metsights_service,
        notifications_service=NotificationsService(NotificationsRepository()),
        assessments_service=assessments_service,
        sync_service=sync_service,
        send_notifications=False,
        user_ids={199302},
    )

    assert result["loaded"] == 1
    push_mock.assert_not_called()
