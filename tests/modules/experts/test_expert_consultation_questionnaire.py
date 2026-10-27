"""Expert portal consultation questionnaire: SuperShyft categories only."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from modules.assessments.models import (
    AssessmentInstance,
    AssessmentPackage,
    AssessmentPackageCategory,
)
from modules.engagements.models import Engagement, EngagementParticipant
from modules.experts.models import ConsultationBooking, Expert
from modules.questionnaire.models import (
    QuestionnaireCategory,
    QuestionnaireCategoryQuestion,
    QuestionnaireDefinition,
)
from modules.users.models import User
from tests.helpers.auth import partner_auth_header, seed_partner


async def _seed_expert(test_db_session, *, partner_id: int) -> Expert:
    partner = await seed_partner(
        test_db_session,
        partner_id=partner_id,
        role="expert",
        phone=f"786{partner_id:07d}"[:15],
        email=f"expertq{partner_id}@test.example",
        commit=False,
    )
    expert = Expert(
        partner_id=partner_id,
        expert_type="doctor",
        specialization="General medicine",
        status="active",
    )
    test_db_session.add(expert)
    await test_db_session.flush()
    return expert


@pytest.mark.asyncio
async def test_portal_consultation_questionnaire_supershyft_only(async_client, test_db_session):
    participant_user_id = 78601
    engagement_id = 7860
    participant_id = 78601
    consultation_id = 786001
    package_id = 7861
    ss_category_id = 7862
    ms_category_id = 7863
    assessment_instance_id = 7864

    expert = await _seed_expert(test_db_session, partner_id=78600)

    test_db_session.add(
        User(
            user_id=participant_user_id,
            age=30,
            phone="786010000000",
            status="active",
        )
    )
    test_db_session.add(
        AssessmentPackage(
            package_id=package_id,
            package_code="METSIGHTS_BASIC",
            display_name="MetSights Basic",
            assessment_type_code="1",
            status="active",
        )
    )
    ss_key = "expert-portal-ss-7862"
    ms_key = "expert-portal-ms-7863"
    test_db_session.add(
        QuestionnaireCategory(
            category_id=ss_category_id,
            category_key=ss_key,
            display_name="Anthropometry",
            category_of="supershyft",
            status="active",
        )
    )
    test_db_session.add(
        QuestionnaireCategory(
            category_id=ms_category_id,
            category_key=ms_key,
            display_name="Physical Measurement",
            category_of="metsights",
            status="active",
        )
    )
    test_db_session.add(
        QuestionnaireDefinition(
            question_id=7865,
            question_key="expert-portal-q-7865",
            question_text="What is your height?",
            question_type="text",
            status="active",
        )
    )
    await test_db_session.flush()

    test_db_session.add(
        AssessmentPackageCategory(id=7866, package_id=package_id, category_id=ss_category_id)
    )
    test_db_session.add(
        AssessmentPackageCategory(id=7867, package_id=package_id, category_id=ms_category_id)
    )
    test_db_session.add(
        QuestionnaireCategoryQuestion(
            id=7868,
            category_id=ss_category_id,
            question_id=7865,
            display_order=1,
        )
    )
    test_db_session.add(
        Engagement(
            engagement_id=engagement_id,
            engagement_name="Q Consult",
            engagement_code="Q7860",
            engagement_type=1,
            consultations={"doctor": True},
            assessment_package_id=package_id,
            diagnostic_package_id=1,
            city="BLR",
            slot_duration=20,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=7),
            status="running",
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        EngagementParticipant(
            engagement_participant_id=participant_id,
            engagement_id=engagement_id,
            user_id=participant_user_id,
            booked_by_user_id=participant_user_id,
            consultation_booking_ids=[consultation_id],
        )
    )
    test_db_session.add(
        AssessmentInstance(
            assessment_instance_id=assessment_instance_id,
            user_id=participant_user_id,
            package_id=package_id,
            engagement_id=engagement_id,
            status="active",
        )
    )
    past_slot = datetime.now() - timedelta(hours=1)
    test_db_session.add(
        ConsultationBooking(
            consultation_id=consultation_id,
            engagement_participant_id=participant_id,
            expert_type="doctor",
            expert_id=expert.expert_id,
            want=True,
            consultation_date=past_slot.date(),
            consultation_slot=past_slot.strftime("%H:%M"),
            done=False,
            consent={"bio_ai": False, "blood_report": False, "questionnaire": True},
        )
    )
    await test_db_session.commit()

    headers = partner_auth_header(expert.partner_id)
    response = await async_client.get(
        f"/experts/portal/consultations/{consultation_id}/questionnaire",
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["consultation_id"] == consultation_id
    assert len(data["assessments"]) == 1
    categories = data["assessments"][0]["categories"]
    category_keys = {c["category_key"] for c in categories}
    assert ss_key in category_keys
    assert ms_key not in category_keys
    for cat in categories:
        assert cat.get("category_of") == "supershyft"
