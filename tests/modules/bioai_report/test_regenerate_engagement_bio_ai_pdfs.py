"""Tests for regenerate_engagement_bio_ai_pdfs job."""

from __future__ import annotations

from datetime import date, time, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from modules.assessments.models import AssessmentInstance
from modules.bioai_report.regenerate_engagement_bio_ai_pdfs import (
    regenerate_engagement_bio_ai_pdfs,
)
from modules.engagements.models import Engagement, EngagementParticipant
from modules.reports.models import IndividualHealthReport
from modules.users.models import User


async def _seed_participant(
    test_db_session,
    *,
    user_id: int,
    engagement_id: int,
    assessment_id: int,
    report_url: str | None = "https://bio-ai-reports.supershyft.com/r/test-slug",
    assessment_type_code: str = "2",
    package_id: int = 1,
    create_engagement: bool = True,
):
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_types (code, display_name, is_active) "
            "VALUES ('regen_eng_pdf', 'Regen Eng PDF', true) ON CONFLICT (code) DO NOTHING"
        )
    )
    type_row = (
        await test_db_session.execute(
            text("SELECT id FROM engagement_types WHERE code = 'regen_eng_pdf'")
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
            gender="female",
            status="active",
        )
    )
    await test_db_session.flush()
    if create_engagement:
        test_db_session.add(
            Engagement(
                engagement_id=engagement_id,
                engagement_name=f"Engagement {engagement_id}",
                engagement_code=f"ENG-REGEN-PDF-{engagement_id}",
                engagement_type=int(type_row[0]),
                assessment_package_id=package_id,
                diagnostic_package_id=1,
                city="Bengaluru",
                slot_duration=20,
                start_date=date.today() - timedelta(days=7),
                end_date=date.today() + timedelta(days=7),
                status="completed",
            )
        )
        await test_db_session.flush()
    test_db_session.add(
        EngagementParticipant(
            engagement_id=engagement_id,
            user_id=user_id,
            engagement_date=date.today() - timedelta(days=1),
            slot_start_time=time(9, 0),
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
async def test_regenerate_engagement_candidates_with_report_url(test_db_session):
    await _seed_participant(
        test_db_session,
        user_id=89001,
        engagement_id=89001,
        assessment_id=89001,
    )
    await _seed_participant(
        test_db_session,
        user_id=89002,
        engagement_id=89001,
        assessment_id=89002,
        create_engagement=False,
    )
    result = await regenerate_engagement_bio_ai_pdfs(
        test_db_session,
        engagement_id=89001,
        dry_run=True,
    )
    assert result["matched"] == 2
    assert all(detail["action"] == "dry_run" for detail in result["details"])


@pytest.mark.asyncio
async def test_regenerate_engagement_skips_without_report_url(test_db_session):
    await _seed_participant(
        test_db_session,
        user_id=89003,
        engagement_id=89003,
        assessment_id=89003,
        report_url=None,
    )
    result = await regenerate_engagement_bio_ai_pdfs(
        test_db_session,
        engagement_id=89003,
        dry_run=True,
    )
    assert result["matched"] == 0


@pytest.mark.asyncio
async def test_regenerate_engagement_calls_pdf_regenerate(test_db_session, monkeypatch):
    await _seed_participant(
        test_db_session,
        user_id=89004,
        engagement_id=89004,
        assessment_id=89004,
        report_url="https://bio-ai-reports.supershyft.com/r/keep-slug",
    )
    regenerate_mock = AsyncMock(
        return_value="https://bio-ai-reports.supershyft.com/r/keep-slug"
    )
    monkeypatch.setattr(
        "modules.bioai_report.regenerate_engagement_bio_ai_pdfs.regenerate_permanent_bio_ai_report_url",
        regenerate_mock,
    )

    result = await regenerate_engagement_bio_ai_pdfs(
        test_db_session,
        engagement_id=89004,
    )
    assert result["regenerated"] == 1
    regenerate_mock.assert_awaited_once_with(
        test_db_session,
        assessment_instance_id=89004,
        report_url="https://bio-ai-reports.supershyft.com/r/keep-slug",
        engagement_id=89004,
        user_id=89004,
    )


@pytest.mark.asyncio
async def test_regenerate_engagement_skips_non_bio_ai_type(test_db_session):
    await _seed_participant(
        test_db_session,
        user_id=89005,
        engagement_id=89005,
        assessment_id=89005,
        assessment_type_code="7",
    )
    result = await regenerate_engagement_bio_ai_pdfs(
        test_db_session,
        engagement_id=89005,
        dry_run=True,
    )
    assert result["matched"] == 1
    assert result["skipped"] == 1
    assert "not BioAI" in result["details"][0]["reason"]
