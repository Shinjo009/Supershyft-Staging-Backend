"""Ensure one individual_health_report row per assessment instance."""

from __future__ import annotations

from datetime import date, time, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, text

from modules.metsights.service import MetsightsService
from modules.notifications.load_bioai_reports import load_bioai_reports
from modules.notifications.load_blood_reports import _get_or_create_ihr
from modules.notifications.repository import NotificationsRepository
from modules.notifications.service import NotificationsService
from modules.reports.models import IndividualHealthReport
from modules.reports.repository import ReportsRepository
from modules.users.models import User


async def _seed_pro_participant(
    test_db_session,
    *,
    user_id: int,
    engagement_id: int,
    assessment_id: int,
    booking_id: str = "BOOK-DUP-TEST",
    metsights_record_id: str = "MS-DUP-TEST",
):
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_types (code, display_name, is_active) "
            "VALUES ('dup_ihr', 'Dup IHR', true) ON CONFLICT (code) DO NOTHING"
        )
    )
    type_row = (
        await test_db_session.execute(text("SELECT id FROM engagement_types WHERE code = 'dup_ihr'"))
    ).one()
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, package_name, diagnostic_provider, status) "
            "VALUES (1, 'Test Diagnostic', 'test_provider', 'active') "
            "ON CONFLICT (diagnostic_package_id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, assessment_type_code, status) "
            "VALUES (1, 'PRO', 'Pro', '2', 'active') "
            "ON CONFLICT (package_id) DO UPDATE SET assessment_type_code = EXCLUDED.assessment_type_code"
        )
    )
    test_db_session.add(
        User(
            user_id=user_id,
            first_name="Dup",
            last_name="Test",
            phone=f"{user_id:010d}",
            age=30,
            gender="female",
            status="active",
        )
    )
    from modules.engagements.models import Engagement, EngagementParticipant
    from modules.assessments.models import AssessmentInstance

    test_db_session.add(
        Engagement(
            engagement_id=engagement_id,
            engagement_name=f"Dup IHR {engagement_id}",
            engagement_code=f"ENG-DUP-{engagement_id}",
            engagement_type=int(type_row[0]),
            assessment_package_id=1,
            diagnostic_package_id=1,
            city="Bengaluru",
            slot_duration=20,
            start_date=date.today() - timedelta(days=7),
            end_date=date.today() + timedelta(days=7),
            status="running",
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
            package_id=1,
            engagement_id=engagement_id,
            status="active",
            metsights_record_id=metsights_record_id,
        )
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_get_or_create_ihr_with_null_id_reuses_existing_assessment_row(
    test_db_session,
):
    user_id, engagement_id, assessment_id = 99175241, 99175241, 99175241
    await _seed_pro_participant(
        test_db_session,
        user_id=user_id,
        engagement_id=engagement_id,
        assessment_id=assessment_id,
    )

    first = await _get_or_create_ihr(
        test_db_session,
        ihr_id=None,
        user_id=user_id,
        engagement_id=engagement_id,
        instance_id=assessment_id,
    )
    first.diagnostic_report_url = "https://supershyft.com/reports/FirstBloodPdfxxxxxx.pdf"
    first.report_url = "https://bio-ai-reports.supershyft.com/r/FirstSlugxxxxxxxxxx"
    await test_db_session.commit()

    second = await _get_or_create_ihr(
        test_db_session,
        ihr_id=None,
        user_id=user_id,
        engagement_id=engagement_id,
        instance_id=assessment_id,
    )
    second.diagnostic_report_url = "https://supershyft.com/reports/SecondBloodPdfxxxxx.pdf"
    await test_db_session.commit()

    assert first.report_id == second.report_id
    rows = (
        await test_db_session.execute(
            select(IndividualHealthReport)
            .where(IndividualHealthReport.assessment_instance_id == assessment_id)
            .order_by(IndividualHealthReport.report_id.asc())
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].diagnostic_report_url == "https://supershyft.com/reports/SecondBloodPdfxxxxx.pdf"


@pytest.mark.asyncio
async def test_repository_get_or_create_is_idempotent(test_db_session):
    user_id, engagement_id, assessment_id = 99175244, 99175244, 99175244
    await _seed_pro_participant(
        test_db_session,
        user_id=user_id,
        engagement_id=engagement_id,
        assessment_id=assessment_id,
    )
    repo = ReportsRepository()
    first = await repo.get_or_create_individual_report_by_assessment(
        test_db_session,
        user_id=user_id,
        engagement_id=engagement_id,
        assessment_instance_id=assessment_id,
    )
    second = await repo.get_or_create_individual_report_by_assessment(
        test_db_session,
        user_id=user_id,
        engagement_id=engagement_id,
        assessment_instance_id=assessment_id,
    )
    assert first.report_id == second.report_id


@pytest.mark.asyncio
async def test_concurrent_style_load_bioai_does_not_create_second_row(
    test_db_session,
    monkeypatch,
):
    user_id, engagement_id, assessment_id = 99175242, 99175242, 99175242
    await _seed_pro_participant(
        test_db_session,
        user_id=user_id,
        engagement_id=engagement_id,
        assessment_id=assessment_id,
        booking_id="BOOK-DUP-BIOAI",
        metsights_record_id="MS-DUP-BIOAI",
    )

    metsights = MetsightsService(client=AsyncMock())
    metsights.get_blood_parameters = AsyncMock(return_value={"is_complete": True})
    metsights.get_report = AsyncMock(
        return_value={
            "id": "MS-DUP-BIOAI",
            "assessment_type": "pro",
            "metabolic_score": 70,
            "diseases": [],
        }
    )

    monkeypatch.setattr(
        "modules.notifications.load_bioai_reports.register_permanent_bio_ai_report_url",
        AsyncMock(return_value="https://bio-ai-reports.supershyft.com/r/BioDupSlug1xxxxxxxxx"),
    )

    async def _tracked_call(*_a, operation=None, **_k):
        if operation is None:
            return None
        result = operation()
        if hasattr(result, "__await__"):
            return await result
        return result

    monkeypatch.setattr(
        "modules.notifications.load_bioai_reports.tracked_integration_call",
        _tracked_call,
    )
    monkeypatch.setattr(
        "modules.notifications.load_bioai_reports._fetch_metsights_report_json",
        AsyncMock(
            return_value={
                "id": "MS-DUP-BIOAI",
                "assessment_type": "pro",
                "metabolic_score": 70,
                "diseases": [],
            }
        ),
    )

    notifications = NotificationsService(NotificationsRepository())
    notifications.dispatch = AsyncMock(return_value=None)

    await load_bioai_reports(
        test_db_session,
        metsights_service=metsights,
        notifications_service=notifications,
        send_notifications=False,
        user_ids={user_id},
        engagement_id=engagement_id,
    )
    await test_db_session.commit()

    await _get_or_create_ihr(
        test_db_session,
        ihr_id=None,
        user_id=user_id,
        engagement_id=engagement_id,
        instance_id=assessment_id,
    )
    await test_db_session.commit()

    count = (
        await test_db_session.execute(
            select(func.count())
            .select_from(IndividualHealthReport)
            .where(IndividualHealthReport.assessment_instance_id == assessment_id)
        )
    ).scalar_one()
    assert int(count) == 1


@pytest.mark.asyncio
async def test_load_blood_metadata_refresh_with_null_ihr_id_reuses_existing_row(
    test_db_session,
):
    user_id, engagement_id, assessment_id = 99175243, 99175243, 99175243
    await _seed_pro_participant(
        test_db_session,
        user_id=user_id,
        engagement_id=engagement_id,
        assessment_id=assessment_id,
        booking_id="BOOK-DUP-BLOOD",
    )

    test_db_session.add(
        IndividualHealthReport(
            user_id=user_id,
            engagement_id=engagement_id,
            assessment_instance_id=assessment_id,
            reports={"id": "x", "metabolic_score": 1},
            report_url="https://bio-ai-reports.supershyft.com/r/SharedSlugxxxxxxxxxxx",
            diagnostic_report_url="https://supershyft.com/reports/OldBloodPdfxxxxxxxxx.pdf",
            blood_parameters=[{"group": "x"}],
        )
    )
    await test_db_session.commit()

    ihr = await _get_or_create_ihr(
        test_db_session,
        ihr_id=None,
        user_id=user_id,
        engagement_id=engagement_id,
        instance_id=assessment_id,
    )
    ihr.diagnostic_report_url = "https://supershyft.com/reports/NewBloodPdfxxxxxxxxx.pdf"
    await test_db_session.commit()

    count = (
        await test_db_session.execute(
            select(func.count())
            .select_from(IndividualHealthReport)
            .where(IndividualHealthReport.assessment_instance_id == assessment_id)
        )
    ).scalar_one()
    assert int(count) == 1
