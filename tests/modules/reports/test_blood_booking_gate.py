"""Tests for archived diagnostic blood report gate helpers."""

from __future__ import annotations

import pytest

from core.config import settings
from modules.reports.blood_booking_reports import (
    has_archived_diagnostic_blood_report,
    require_archived_diagnostic_blood_report,
)
from core.exceptions import AppError
from tests.helpers.archived_blood_report import seed_archived_diagnostic_blood_report
from tests.modules.notifications.test_load_cron_sync_logs import _seed_bioai_participant


@pytest.mark.asyncio
async def test_has_archived_diagnostic_blood_report_false_without_pdf(test_db_session):
    await _seed_bioai_participant(
        test_db_session,
        user_id=991001,
        engagement_id=991001,
        assessment_id=991001,
        bioai_notification=None,
        seed_archived_blood=False,
    )
    assert not await has_archived_diagnostic_blood_report(
        test_db_session,
        user_id=991001,
        engagement_id=991001,
    )


@pytest.mark.asyncio
async def test_require_archived_diagnostic_blood_report_raises_without_pdf(test_db_session):
    await _seed_bioai_participant(
        test_db_session,
        user_id=991002,
        engagement_id=991002,
        assessment_id=991002,
        bioai_notification=None,
        seed_archived_blood=False,
    )
    with pytest.raises(AppError) as exc_info:
        await require_archived_diagnostic_blood_report(
            test_db_session,
            user_id=991002,
            engagement_id=991002,
        )
    assert exc_info.value.error_code == "INVALID_STATE"


@pytest.mark.asyncio
async def test_has_archived_diagnostic_blood_report_true_with_pdf(test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "BLOOD_REPORTS_BASE_URL", "https://supershyft.com/reports")
    await _seed_bioai_participant(
        test_db_session,
        user_id=991003,
        engagement_id=991003,
        assessment_id=991003,
        bioai_notification=None,
        seed_archived_blood=False,
    )
    await seed_archived_diagnostic_blood_report(
        test_db_session,
        user_id=991003,
        engagement_id=991003,
    )
    assert await has_archived_diagnostic_blood_report(
        test_db_session,
        user_id=991003,
        engagement_id=991003,
    )


@pytest.mark.asyncio
async def test_has_archived_diagnostic_blood_report_true_with_healthians_url_when_debug(
    test_db_session, monkeypatch
):
    healthians_url = "https://s3.amazonaws.com/healthians/signed/report.pdf"
    monkeypatch.setattr(settings, "DEBUG", True)
    await _seed_bioai_participant(
        test_db_session,
        user_id=991004,
        engagement_id=991004,
        assessment_id=991004,
        bioai_notification=None,
        seed_archived_blood=False,
    )
    await seed_archived_diagnostic_blood_report(
        test_db_session,
        user_id=991004,
        engagement_id=991004,
        diagnostic_report_url=healthians_url,
    )
    assert await has_archived_diagnostic_blood_report(
        test_db_session,
        user_id=991004,
        engagement_id=991004,
    )
