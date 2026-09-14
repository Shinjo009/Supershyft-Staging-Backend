"""Tests for regenerate_bioai_reports cron job."""

from __future__ import annotations

from datetime import date, time, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from modules.assessments.models import AssessmentInstance
from modules.engagements.models import Engagement, EngagementParticipant
from modules.metsights.client import MetsightsClient
from modules.metsights.service import MetsightsService
from modules.notifications.regenerate_bioai_reports import regenerate_bioai_reports
from modules.reports.models import IndividualHealthReport
from modules.users.models import User
from db.seed.blood_parameters_registry import ADVANCED_BLOOD_PARAMETER_CATEGORY_KEY


async def _seed_regenerate_participant(
    test_db_session,
    *,
    user_id: int,
    engagement_id: int,
    assessment_id: int,
    gender: str = "female",
    booking_id: str | None = "BOOK123",
    report_url: str | None = "https://bio-ai-reports.supershyft.com/r/test-slug",
    engagement_status: str = "running",
    package_id: int = 1,
    assessment_type_code: str = "2",
    create_engagement: bool = True,
):
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_types (code, display_name, is_active) "
            "VALUES ('regen_bioai', 'Regen BioAI', true) ON CONFLICT (code) DO NOTHING"
        )
    )
    type_row = (
        await test_db_session.execute(
            text("SELECT id FROM engagement_types WHERE code = 'regen_bioai'")
        )
    ).one()
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, package_name, diagnostic_provider, status) "
            "VALUES (1, 'Test Diagnostic', 'test_provider', 'active') ON CONFLICT DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, assessment_type_code, status) "
            "VALUES (:pid, :pcode, :dname, :tcode, 'active') "
            "ON CONFLICT (package_id) DO UPDATE SET assessment_type_code = EXCLUDED.assessment_type_code"
        ),
        {
            "pid": package_id,
            "pcode": f"PKG{package_id}",
            "dname": f"Package {package_id}",
            "tcode": assessment_type_code,
        },
    )
    test_db_session.add(
        User(
            user_id=user_id,
            first_name="Test",
            last_name="User",
            phone=f"{user_id:010d}",
            age=30,
            gender=gender,
            status="active",
        )
    )
    await test_db_session.flush()
    if create_engagement:
        test_db_session.add(
            Engagement(
                engagement_id=engagement_id,
                engagement_name=f"Engagement {engagement_id}",
                engagement_code=f"ENG-REGEN-{engagement_id}",
                engagement_type=int(type_row[0]),
                assessment_package_id=package_id,
                diagnostic_package_id=1,
                city="Bengaluru",
                slot_duration=20,
                start_date=date.today() - timedelta(days=7),
                end_date=date.today() + timedelta(days=7),
                status=engagement_status,
            )
        )
        await test_db_session.flush()
    test_db_session.add(
        EngagementParticipant(
            engagement_id=engagement_id,
            user_id=user_id,
            engagement_date=date.today() - timedelta(days=1),
            slot_start_time=time(9, 0),
            booking_id=booking_id,
        )
    )
    test_db_session.add(
        AssessmentInstance(
            assessment_instance_id=assessment_id,
            user_id=user_id,
            package_id=package_id,
            engagement_id=engagement_id,
            status="completed",
            metsights_record_id=f"MS-{assessment_id}",
        )
    )
    if report_url is not None:
        test_db_session.add(
            IndividualHealthReport(
                user_id=user_id,
                engagement_id=engagement_id,
                assessment_instance_id=assessment_id,
                reports={"record_id": f"MS-{assessment_id}"},
                report_url=report_url,
            )
        )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_regenerate_candidates_include_female_with_booking_and_report_url(test_db_session):
    await _seed_regenerate_participant(
        test_db_session,
        user_id=88001,
        engagement_id=88001,
        assessment_id=88001,
        gender="female",
        booking_id="BOOK-F-1",
    )
    await _seed_regenerate_participant(
        test_db_session,
        user_id=88002,
        engagement_id=88001,
        assessment_id=88002,
        gender="male",
        booking_id="BOOK-M-1",
        create_engagement=False,
    )
    metsights_service = MetsightsService(client=MetsightsClient())
    result = await regenerate_bioai_reports(
        test_db_session,
        metsights_service=metsights_service,
        dry_run=True,
        engagement_id=88001,
    )
    assert result["matched"] == 1
    assert result["details"][0]["user_id"] == 88001
    assert result["details"][0]["action"] == "dry_run"


@pytest.mark.asyncio
async def test_regenerate_skips_without_report_url(test_db_session):
    await _seed_regenerate_participant(
        test_db_session,
        user_id=88003,
        engagement_id=88003,
        assessment_id=88003,
        report_url=None,
    )
    metsights_service = MetsightsService(client=MetsightsClient())
    result = await regenerate_bioai_reports(
        test_db_session,
        metsights_service=metsights_service,
        dry_run=True,
        engagement_id=88003,
    )
    assert result["matched"] == 0


@pytest.mark.asyncio
async def test_regenerate_updates_reports_without_changing_report_url(test_db_session, monkeypatch):
    await _seed_regenerate_participant(
        test_db_session,
        user_id=88004,
        engagement_id=88004,
        assessment_id=88004,
        report_url="https://bio-ai-reports.supershyft.com/r/keep-slug",
    )
    metsights_service = MetsightsService(client=MetsightsClient())
    assessments_service = AsyncMock()
    assessments_service.draft_blood_parameters_from_report = AsyncMock(
        return_value={"responses_drafted": 2}
    )
    assessments_service.is_vitals_blood_pressure_missing = AsyncMock(return_value=True)
    assessments_service.draft_vitals_blood_pressure_fallbacks = AsyncMock(
        return_value={"responses_drafted": 2, "fallback_keys": ["systolic_blood_pressure", "diastolic_blood_pressure"]}
    )
    sync_service = AsyncMock()
    sync_service._push_category_to_metsights = AsyncMock(
        return_value={"fields_pushed": ["haemoglobin"]}
    )

    async def _fake_blood_params(*, record_id: str):
        return {"is_complete": True}

    async def _fake_report(*, record_id: str, assessment_type_code: str | None):
        return {"record_id": record_id, "refreshed": True}

    regenerate_mock = AsyncMock(return_value="https://bio-ai-reports.supershyft.com/r/keep-slug")
    monkeypatch.setattr(metsights_service, "get_blood_parameters", _fake_blood_params)
    monkeypatch.setattr(metsights_service, "get_report", _fake_report)
    monkeypatch.setattr(
        "modules.notifications.regenerate_bioai_reports.regenerate_permanent_bio_ai_report_url",
        regenerate_mock,
    )
    monkeypatch.setattr(
        "modules.notifications.regenerate_bioai_reports._metsights_category_keys_for_package",
        AsyncMock(return_value=["physical-measurement", "vitals", "blood-parameters"]),
    )

    result = await regenerate_bioai_reports(
        test_db_session,
        metsights_service=metsights_service,
        assessments_service=assessments_service,
        sync_service=sync_service,
        engagement_id=88004,
    )
    assert result["regenerated"] == 1
    assessments_service.draft_blood_parameters_from_report.assert_awaited_once()
    assessments_service.draft_vitals_blood_pressure_fallbacks.assert_awaited_once()
    assert sync_service._push_category_to_metsights.await_count == 3
    regenerate_mock.assert_awaited_once()

    row = (
        await test_db_session.execute(
            text(
                "SELECT reports, report_url FROM individual_health_report "
                "WHERE user_id = 88004 AND engagement_id = 88004"
            )
        )
    ).one()
    assert row[0]["refreshed"] is True
    assert row[1] == "https://bio-ai-reports.supershyft.com/r/keep-slug"


@pytest.mark.asyncio
async def test_regenerate_includes_completed_engagement_when_engagement_id_set(test_db_session):
    await _seed_regenerate_participant(
        test_db_session,
        user_id=88006,
        engagement_id=88006,
        assessment_id=88006,
        engagement_status="completed",
    )
    metsights_service = MetsightsService(client=MetsightsClient())
    result = await regenerate_bioai_reports(
        test_db_session,
        metsights_service=metsights_service,
        dry_run=True,
        engagement_id=88006,
    )
    assert result["matched"] == 1


@pytest.mark.asyncio
async def test_regenerate_excludes_completed_engagement_without_engagement_id(test_db_session):
    await _seed_regenerate_participant(
        test_db_session,
        user_id=88007,
        engagement_id=88007,
        assessment_id=88007,
        engagement_status="completed",
    )
    metsights_service = MetsightsService(client=MetsightsClient())
    result = await regenerate_bioai_reports(
        test_db_session,
        metsights_service=metsights_service,
        dry_run=True,
    )
    assert result["matched"] == 0


@pytest.mark.asyncio
async def test_regenerate_retries_vitals_push_after_default_bp_draft(test_db_session, monkeypatch):
    await _seed_regenerate_participant(
        test_db_session,
        user_id=88008,
        engagement_id=88008,
        assessment_id=88008,
    )
    metsights_service = MetsightsService(client=MetsightsClient())
    assessments_service = AsyncMock()
    assessments_service.draft_blood_parameters_from_report = AsyncMock(
        return_value={"responses_drafted": 1}
    )
    assessments_service.is_vitals_blood_pressure_missing = AsyncMock(return_value=False)
    assessments_service.draft_vitals_blood_pressure_fallbacks = AsyncMock(
        return_value={"responses_drafted": 2}
    )
    sync_service = AsyncMock()
    vitals_error = Exception(
        "Missing required fields for vitals: diastolic_blood_pressure, systolic_blood_pressure."
    )
    vitals_push_calls = {"count": 0}

    async def _fake_push(db, *, assessment_instance_id, user_id, category_key):
        if category_key == "vitals":
            vitals_push_calls["count"] += 1
            if vitals_push_calls["count"] == 1:
                raise vitals_error
        return {"fields_pushed": ["field"]}

    sync_service._push_category_to_metsights = AsyncMock(side_effect=_fake_push)

    async def _fake_blood_params(*, record_id: str):
        return {"is_complete": True}

    async def _fake_report(*, record_id: str, assessment_type_code: str | None):
        return {"record_id": record_id, "refreshed": True}

    monkeypatch.setattr(metsights_service, "get_blood_parameters", _fake_blood_params)
    monkeypatch.setattr(metsights_service, "get_report", _fake_report)
    monkeypatch.setattr(
        "modules.notifications.regenerate_bioai_reports.regenerate_permanent_bio_ai_report_url",
        AsyncMock(return_value="https://bio-ai-reports.supershyft.com/r/test-slug"),
    )
    monkeypatch.setattr(
        "modules.notifications.regenerate_bioai_reports._metsights_category_keys_for_package",
        AsyncMock(return_value=["vitals"]),
    )

    result = await regenerate_bioai_reports(
        test_db_session,
        metsights_service=metsights_service,
        assessments_service=assessments_service,
        sync_service=sync_service,
        engagement_id=88008,
    )
    assert result["regenerated"] == 1
    assessments_service.draft_vitals_blood_pressure_fallbacks.assert_awaited_once()
    assert sync_service._push_category_to_metsights.await_count == 2


@pytest.mark.asyncio
async def test_regenerate_skips_advanced_blood_push_failure_and_continues(
    test_db_session,
    monkeypatch,
):
    await _seed_regenerate_participant(
        test_db_session,
        user_id=88009,
        engagement_id=88009,
        assessment_id=88009,
    )
    metsights_service = MetsightsService(client=MetsightsClient())
    assessments_service = AsyncMock()
    assessments_service.draft_blood_parameters_from_report = AsyncMock(
        return_value={"responses_drafted": 1}
    )
    assessments_service.is_vitals_blood_pressure_missing = AsyncMock(return_value=False)
    sync_service = AsyncMock()

    async def _fake_push(db, *, assessment_instance_id, user_id, category_key):
        if category_key == ADVANCED_BLOOD_PARAMETER_CATEGORY_KEY:
            raise Exception("Metsights record not found")
        return {"fields_pushed": ["field"]}

    sync_service._push_category_to_metsights = AsyncMock(side_effect=_fake_push)

    async def _fake_blood_params(*, record_id: str):
        return {"is_complete": True}

    async def _fake_report(*, record_id: str, assessment_type_code: str | None):
        return {"record_id": record_id, "refreshed": True}

    regenerate_mock = AsyncMock(return_value="https://bio-ai-reports.supershyft.com/r/test-slug")
    monkeypatch.setattr(metsights_service, "get_blood_parameters", _fake_blood_params)
    monkeypatch.setattr(metsights_service, "get_report", _fake_report)
    monkeypatch.setattr(
        "modules.notifications.regenerate_bioai_reports.regenerate_permanent_bio_ai_report_url",
        regenerate_mock,
    )
    monkeypatch.setattr(
        "modules.notifications.regenerate_bioai_reports._metsights_category_keys_for_package",
        AsyncMock(return_value=["blood-parameters", ADVANCED_BLOOD_PARAMETER_CATEGORY_KEY]),
    )

    result = await regenerate_bioai_reports(
        test_db_session,
        metsights_service=metsights_service,
        assessments_service=assessments_service,
        sync_service=sync_service,
        engagement_id=88009,
    )
    assert result["regenerated"] == 1
    assert result["failed"] == 0
    regenerate_mock.assert_awaited_once()
    skipped = [d for d in result["details"] if d["action"] == "skipped"]
    assert any("advanced-blood-parameters" in d["reason"] for d in skipped)


@pytest.mark.asyncio
async def test_regenerate_dry_run_mentions_metsights_repush(test_db_session):
    await _seed_regenerate_participant(
        test_db_session,
        user_id=88005,
        engagement_id=88005,
        assessment_id=88005,
    )
    metsights_service = MetsightsService(client=MetsightsClient())
    result = await regenerate_bioai_reports(
        test_db_session,
        metsights_service=metsights_service,
        dry_run=True,
        engagement_id=88005,
    )
    assert result["matched"] == 1
    reason = result["details"][0]["reason"]
    assert "would_draft_blood_questionnaires" in reason
    assert "would_repush_all_metsights_categories" in reason
