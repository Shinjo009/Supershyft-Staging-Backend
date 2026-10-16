"""Tests for remediate_bad_bioai_batch maintenance job."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text

from db.seed.blood_parameters_registry import BLOOD_PARAMETER_CATEGORY_KEY
from modules.assessments.models import AssessmentInstance
from modules.engagements.models import Engagement, EngagementParticipant
from modules.maintenance.remediate_bad_bioai_batch import remediate_bad_bioai_batch
from modules.questionnaire.models import (
    QuestionnaireCategory,
    QuestionnaireDefinition,
    QuestionnaireResponse,
)
from modules.reports.models import IndividualHealthReport
from modules.users.models import User
from tests.helpers.archived_blood_report import seed_archived_diagnostic_blood_report


async def _seed_bad_batch_participant(
    test_db_session,
    *,
    user_id: int,
    engagement_id: int,
    assessment_id: int,
    with_archived_blood: bool = False,
    package_id: int = 1,
):
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_types (code, display_name, is_active) "
            "VALUES ('remediate_bioai', 'Remediate BioAI', true) ON CONFLICT (code) DO NOTHING"
        )
    )
    type_row = (
        await test_db_session.execute(
            text("SELECT id FROM engagement_types WHERE code = 'remediate_bioai'")
        )
    ).one()
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, package_name, diagnostic_provider, status) "
            "VALUES (1, 'Test Diagnostic', 'healthians', 1) ON CONFLICT (diagnostic_package_id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, assessment_type_code, "
            "subscription_id, status) "
            "VALUES (:pid, :pcode, :dname, '2', 'sub-primary-1', 1) "
            "ON CONFLICT (package_id) DO UPDATE SET "
            "assessment_type_code = EXCLUDED.assessment_type_code, "
            "subscription_id = EXCLUDED.subscription_id"
        ),
        {"pid": package_id, "pcode": f"PKG{package_id}", "dname": f"Package {package_id}"},
    )
    test_db_session.add(
        User(
            user_id=user_id,
            first_name="Remediate",
            last_name="User",
            phone=f"{user_id:010d}",
            age=30,
            status="active",
            metsights_profile_id="profile-remediate-1",
        )
    )
    test_db_session.add(
        Engagement(
            engagement_id=engagement_id,
            engagement_name=f"Engagement {engagement_id}",
            engagement_code=f"ENG-REMED-{engagement_id}",
            engagement_type=int(type_row[0]),
            assessment_package_id=package_id,
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
            booked_by_user_id=user_id,
        )
    )
    test_db_session.add(
        AssessmentInstance(
            assessment_instance_id=assessment_id,
            user_id=user_id,
            package_id=package_id,
            engagement_id=engagement_id,
            status="completed",
            metsights_record_id=f"MS-OLD-{assessment_id}",
        )
    )
    test_db_session.add(
        IndividualHealthReport(
            user_id=user_id,
            engagement_id=engagement_id,
            assessment_instance_id=assessment_id,
            reports={"record_id": f"MS-OLD-{assessment_id}", "data": {"score": 1}},
            report_url="https://bio-ai-reports.supershyft.com/r/remediate-test",
        )
    )
    await test_db_session.flush()

    blood_category_id = (
        await test_db_session.execute(
            text(
                "SELECT category_id FROM questionnaire_categories "
                "WHERE category_key = :key AND category_of = 'metsights' LIMIT 1"
            ),
            {"key": BLOOD_PARAMETER_CATEGORY_KEY},
        )
    ).scalar_one_or_none()
    if blood_category_id is None:
        blood_category_id = 880010 + assessment_id
        test_db_session.add(
            QuestionnaireCategory(
                category_id=blood_category_id,
                category_key=BLOOD_PARAMETER_CATEGORY_KEY,
                display_name="Blood Parameters",
                category_of="metsights",
                status="active",
            )
        )
    else:
        blood_category_id = int(blood_category_id)

    vitals_category_id = (
        await test_db_session.execute(
            text(
                "SELECT category_id FROM questionnaire_categories "
                "WHERE category_key = 'vitals' AND category_of = 'metsights' LIMIT 1"
            )
        )
    ).scalar_one_or_none()
    if vitals_category_id is None:
        vitals_category_id = 880011 + assessment_id
        test_db_session.add(
            QuestionnaireCategory(
                category_id=vitals_category_id,
                category_key="vitals",
                display_name="Vitals",
                category_of="metsights",
                status="active",
            )
        )
    else:
        vitals_category_id = int(vitals_category_id)

    blood_question_id = (
        await test_db_session.execute(
            text(
                "SELECT question_id FROM questionnaire_definitions "
                "WHERE question_key = 'glucose_fasting' LIMIT 1"
            )
        )
    ).scalar_one_or_none()
    if blood_question_id is None:
        blood_question_id = 880020 + assessment_id
        test_db_session.add(
            QuestionnaireDefinition(
                question_id=blood_question_id,
                question_key="glucose_fasting",
                question_text="Glucose",
                question_type="scale",
                status="active",
            )
        )
    else:
        blood_question_id = int(blood_question_id)

    vitals_question_id = (
        await test_db_session.execute(
            text(
                "SELECT question_id FROM questionnaire_definitions "
                "WHERE question_key = 'systolic_blood_pressure' LIMIT 1"
            )
        )
    ).scalar_one_or_none()
    if vitals_question_id is None:
        vitals_question_id = 880021 + assessment_id
        test_db_session.add(
            QuestionnaireDefinition(
                question_id=vitals_question_id,
                question_key="systolic_blood_pressure",
                question_text="Systolic",
                question_type="scale",
                status="active",
            )
        )
    else:
        vitals_question_id = int(vitals_question_id)

    await test_db_session.flush()

    test_db_session.add(
        QuestionnaireResponse(
            assessment_instance_id=assessment_id,
            question_id=blood_question_id,
            category_ids=[blood_category_id],
            answer={"value": 5.0},
        )
    )
    test_db_session.add(
        QuestionnaireResponse(
            assessment_instance_id=assessment_id,
            question_id=vitals_question_id,
            category_ids=[vitals_category_id],
            answer={"value": 120.0, "unit": "0"},
        )
    )

    await test_db_session.commit()

    if with_archived_blood:
        await seed_archived_diagnostic_blood_report(
            test_db_session,
            user_id=user_id,
            engagement_id=engagement_id,
        )


@pytest.mark.asyncio
async def test_remediate_bad_batch_applies_and_pushes(test_db_session):
    user_id = 880001
    engagement_id = 880001
    assessment_id = 880001
    await _seed_bad_batch_participant(
        test_db_session,
        user_id=user_id,
        engagement_id=engagement_id,
        assessment_id=assessment_id,
    )

    metsights_service = AsyncMock()
    metsights_service.create_record_for_profile = AsyncMock(return_value="MS-NEW-880001")
    sync_service = AsyncMock()
    sync_service.push_questionnaire_for_instance = AsyncMock(
        return_value={"pushed": True, "resources_patched": ["vitals"]},
    )

    result = await remediate_bad_bioai_batch(
        test_db_session,
        engagement_id=engagement_id,
        metsights_service=metsights_service,
        sync_service=sync_service,
        dry_run=False,
    )

    assert result["matched"] == 1
    assert result["remediated"] == 1
    assert result["failed"] == 0
    metsights_service.create_record_for_profile.assert_awaited_once_with(
        profile_id="profile-remediate-1",
        subscription_id="sub-primary-1",
    )
    sync_service.push_questionnaire_for_instance.assert_awaited_once()
    push_kwargs = sync_service.push_questionnaire_for_instance.await_args.kwargs
    assert push_kwargs["assessment_instance_id"] == assessment_id
    assert "vitals" in (push_kwargs.get("categories") or [])

    instance = await test_db_session.get(AssessmentInstance, assessment_id)
    assert instance is not None
    assert instance.metsights_record_id == "MS-NEW-880001"

    ihr = (
        await test_db_session.execute(
            select(IndividualHealthReport).where(
                IndividualHealthReport.assessment_instance_id == assessment_id
            )
        )
    ).scalar_one()
    assert ihr.reports is None
    assert ihr.report_url is None

    blood_category_id = (
        await test_db_session.execute(
            text(
                "SELECT category_id FROM questionnaire_categories "
                "WHERE category_key = :key AND category_of = 'metsights' LIMIT 1"
            ),
            {"key": BLOOD_PARAMETER_CATEGORY_KEY},
        )
    ).scalar_one()
    vitals_category_id = (
        await test_db_session.execute(
            text(
                "SELECT category_id FROM questionnaire_categories "
                "WHERE category_key = 'vitals' AND category_of = 'metsights' LIMIT 1"
            )
        )
    ).scalar_one()
    blood_rows = (
        await test_db_session.execute(
            select(QuestionnaireResponse).where(
                QuestionnaireResponse.assessment_instance_id == assessment_id,
                QuestionnaireResponse.category_ids.any(blood_category_id),
            )
        )
    ).scalars().all()
    assert blood_rows == []

    vitals_rows = (
        await test_db_session.execute(
            select(QuestionnaireResponse).where(
                QuestionnaireResponse.assessment_instance_id == assessment_id,
                QuestionnaireResponse.category_ids.any(vitals_category_id),
            )
        )
    ).scalars().all()
    assert len(vitals_rows) == 1


@pytest.mark.asyncio
async def test_remediate_skips_when_archived_blood_present(test_db_session):
    user_id = 880002
    engagement_id = 880002
    assessment_id = 880002
    await _seed_bad_batch_participant(
        test_db_session,
        user_id=user_id,
        engagement_id=engagement_id,
        assessment_id=assessment_id,
        with_archived_blood=True,
    )

    metsights_service = AsyncMock()
    sync_service = AsyncMock()

    result = await remediate_bad_bioai_batch(
        test_db_session,
        engagement_id=engagement_id,
        metsights_service=metsights_service,
        sync_service=sync_service,
        dry_run=False,
    )

    assert result["matched"] == 0
    metsights_service.create_record_for_profile.assert_not_called()


@pytest.mark.asyncio
async def test_remediate_dry_run_does_not_mutate(test_db_session):
    user_id = 880003
    engagement_id = 880003
    assessment_id = 880003
    await _seed_bad_batch_participant(
        test_db_session,
        user_id=user_id,
        engagement_id=engagement_id,
        assessment_id=assessment_id,
    )

    metsights_service = AsyncMock()
    sync_service = AsyncMock()

    result = await remediate_bad_bioai_batch(
        test_db_session,
        engagement_id=engagement_id,
        metsights_service=metsights_service,
        sync_service=sync_service,
        dry_run=True,
    )

    assert result["matched"] == 1
    assert result["remediated"] == 0
    assert result["skipped"] == 1
    metsights_service.create_record_for_profile.assert_not_called()

    instance = await test_db_session.get(AssessmentInstance, assessment_id)
    assert instance.metsights_record_id == f"MS-OLD-{assessment_id}"
