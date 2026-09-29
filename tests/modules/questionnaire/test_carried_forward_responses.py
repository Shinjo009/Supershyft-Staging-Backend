"""Tests for is_carried_forward questionnaire response behavior."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from modules.assessments.models import AssessmentInstance, AssessmentPackage, AssessmentPackageCategory
from modules.engagements.models import Engagement
from modules.questionnaire.models import (
    QuestionnaireCategory,
    QuestionnaireCategoryQuestion,
    QuestionnaireDefinition,
    QuestionnaireResponse,
)


async def _seed_minimal_category(test_db_session, *, package_id: int, category_id: int, question_id: int):
    test_db_session.add(
        QuestionnaireCategory(
            category_id=category_id,
            category_key="diet-lifestyle-parameters",
            display_name="Diet",
            status="active",
        )
    )
    test_db_session.add(
        QuestionnaireDefinition(
            question_id=question_id,
            question_key="carried_fwd_q",
            question_text="Q",
            question_type="text",
            is_required=True,
            status="active",
        )
    )
    await test_db_session.flush()
    test_db_session.add(AssessmentPackageCategory(package_id=package_id, category_id=category_id))
    test_db_session.add(
        QuestionnaireCategoryQuestion(
            id=category_id * 10,
            category_id=category_id,
            question_id=question_id,
        )
    )
    await test_db_session.commit()


def _auth_header(user_id: int) -> dict[str, str]:
    from tests.helpers.auth import user_auth_header

    return user_auth_header(user_id)


@pytest.mark.asyncio
async def test_get_questionnaire_exposes_is_carried_forward(async_client, test_db_session):
    package_id = 9901
    test_db_session.add(
        AssessmentPackage(
            package_id=package_id,
            package_code="CFWD_PKG",
            display_name="CFWD",
            status="active",
            assessment_type_code="1",
        )
    )
    test_db_session.add(
        Engagement(
            engagement_id=9901,
            engagement_name="CFWD Camp",
            engagement_code="CFWD9901",
            organization_id=None,
            engagement_type=1,
            city="BLR",
            slot_duration=20,
            start_date="2026-02-01",
            end_date="2026-02-01",
            status="running",
        )
    )
    await _seed_minimal_category(
        test_db_session, package_id=package_id, category_id=9901, question_id=9901
    )
    await test_db_session.execute(
        text(
            "INSERT INTO users (user_id, age, phone, status) "
            "VALUES (99001, 30, '7999009901', 1) ON CONFLICT (user_id) DO NOTHING"
        )
    )
    test_db_session.add(
        AssessmentInstance(
            user_id=99001,
            package_id=package_id,
            engagement_id=9901,
            status="active",
        )
    )
    await test_db_session.flush()
    instance_id = (
        await test_db_session.execute(
            text(
                "SELECT assessment_instance_id FROM assessment_instances "
                "WHERE user_id = 99001 LIMIT 1"
            )
        )
    ).scalar_one()
    test_db_session.add(
        QuestionnaireResponse(
            assessment_instance_id=int(instance_id),
            question_id=9901,
            category_ids=[9901],
            answer="from prior camp",
            is_carried_forward=True,
        )
    )
    await test_db_session.commit()

    response = await async_client.get(
        f"/questionnaire/{instance_id}/category/9901",
        headers=_auth_header(99001),
        params={"question": "all"},
    )
    assert response.status_code == 200
    questions = response.json()["data"]["questions"]
    assert len(questions) == 1
    assert questions[0]["is_carried_forward"] is True
    assert questions[0]["answer_source"] == "carried_forward"
    assert questions[0]["answer"] == "from prior camp"
