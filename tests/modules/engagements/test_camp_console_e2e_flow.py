"""End-to-end API flow for on-site camp console (phlebo + camp booking + questionnaires)."""

from __future__ import annotations

from datetime import date, time
from unittest.mock import AsyncMock, patch

import pytest

from core.config import settings
from modules.assessments.models import (
    AssessmentInstance,
    AssessmentPackage,
    AssessmentPackageCategory,
)
from modules.diagnostics.models import DiagnosticPackage
from modules.engagements.models import Engagement
from modules.questionnaire.models import (
    QuestionnaireCategory,
    QuestionnaireCategoryQuestion,
    QuestionnaireDefinition,
)
from modules.users.models import User
from tests.helpers.console_camp import get_current_blood_booking, upsert_camp_participant_with_schedule
from tests.modules.engagements.test_console_routes import (
    _assign_assistant,
    _partner_auth_header,
    _seed_engagement,
    _seed_partner,
)


@pytest.mark.asyncio
async def test_camp_phlebo_console_questionnaire_and_book_flow(
    async_client, test_db_session, monkeypatch
):
    """Assigned phlebo: list camp → participants → assessments → questionnaire → book (mocked Healthians)."""
    monkeypatch.setattr(settings, "HEALTHIANS_CHECKSUM_KEY", "test-checksum-key")

    engagement_id = 8900
    partner_id = 890
    participant_user_id = 89001
    engagement_participant_id = 89001
    assessment_instance_id = 89002
    package_id = 8903
    category_id = 8904

    await _seed_partner(test_db_session, partner_id=partner_id)

    diag = await test_db_session.get(DiagnosticPackage, 8905)
    if diag is None:
        test_db_session.add(
            DiagnosticPackage(
                diagnostic_package_id=8905,
                reference_id="REF8905",
                package_name="Camp Package",
                diagnostic_provider="healthians",
                external_package_code="2002",
                status="active",
                bookings_count=0,
            )
        )
        await test_db_session.flush()

    engagement = await _seed_engagement(test_db_session, engagement_id=engagement_id, status="running")
    engagement.external_camp_id = 89001
    engagement.latitude = 28.6
    engagement.longitude = 77.2
    engagement.pincode = "110001"
    engagement.address = "Camp ground"
    engagement.diagnostic_package_id = 8905

    await _assign_assistant(
        test_db_session,
        assignment_id=89010,
        partner_id=partner_id,
        engagement_id=engagement_id,
    )

    test_db_session.add(
        User(
            user_id=participant_user_id,
            age=32,
            phone="8900100000",
            email="camp.pat@example.com",
            status="active",
            first_name="Camp",
            last_name="Pat",
            gender="male",
            relationship="self",
        )
    )
    await test_db_session.flush()

    await upsert_camp_participant_with_schedule(
        test_db_session,
        engagement_participant_id=engagement_participant_id,
        engagement_id=engagement_id,
        user_id=participant_user_id,
        collection_date=date.today(),
        collection_time=time(7, 30),
    )

    if await test_db_session.get(AssessmentPackage, package_id) is None:
        test_db_session.add(
            AssessmentPackage(
                package_id=package_id,
                package_code="CAMP_PKG",
                display_name="Camp Assessments",
                status="active",
            )
        )
    if await test_db_session.get(QuestionnaireCategory, category_id) is None:
        test_db_session.add(
            QuestionnaireCategory(
                category_id=category_id,
                category_key="physical-measurement",
                display_name="Physical",
                category_of="metsights",
                status="active",
            )
        )
    question_id = 889906
    if await test_db_session.get(QuestionnaireDefinition, question_id) is None:
        test_db_session.add(
            QuestionnaireDefinition(
                question_id=question_id,
                question_key="q_camp_height",
                question_text="Height?",
                question_type="text",
                status="active",
            )
        )
        await test_db_session.flush()
    test_db_session.add(
        AssessmentInstance(
            assessment_instance_id=assessment_instance_id,
            user_id=participant_user_id,
            package_id=package_id,
            engagement_id=engagement_id,
            status="active",
        )
    )
    test_db_session.add(
        AssessmentPackageCategory(id=8907, package_id=package_id, category_id=category_id)
    )
    test_db_session.add(
        QuestionnaireCategoryQuestion(id=889908, category_id=category_id, question_id=question_id)
    )
    await test_db_session.commit()

    headers = _partner_auth_header(partner_id)
    base = f"/engagements/{engagement_id}/console"

    list_res = await async_client.get("/engagements/console/engagements", headers=headers)
    assert list_res.status_code == 200
    assert any(row["engagement_id"] == engagement_id for row in list_res.json()["data"])

    detail_res = await async_client.get(f"{base}", headers=headers)
    assert detail_res.status_code == 200

    parts_res = await async_client.get(f"{base}/participants", headers=headers)
    assert parts_res.status_code == 200
    parts = parts_res.json()["data"]
    assert any(p["user_id"] == participant_user_id for p in parts)

    assess_res = await async_client.get(
        f"{base}/participants/{participant_user_id}/assessments",
        headers=headers,
    )
    assert assess_res.status_code == 200
    assert assess_res.json()["data"][0]["assessment_instance_id"] == assessment_instance_id

    q_res = await async_client.get(
        f"{base}/participants/{participant_user_id}/questionnaire/{assessment_instance_id}/category/{category_id}",
        headers=headers,
    )
    assert q_res.status_code == 200
    assert len(q_res.json()["data"]["questions"]) >= 1

    mock_serviceability = AsyncMock(
        return_value={"status": True, "data": {"zone_id": 42}, "message": "ok"}
    )
    mock_create_booking = AsyncMock(
        return_value={
            "status": True,
            "message": "Booking created",
            "booking_id": "1715890001",
            "lead_id": 1,
        }
    )

    with patch(
        "modules.engagements.console.service.healthians_client.check_serviceability_by_location_v2",
        mock_serviceability,
    ):
        with patch(
            "modules.engagements.console.service.healthians_client.create_booking_v3",
            mock_create_booking,
        ):
            with patch(
                "modules.engagements.console.service.healthians_client.get_access_token",
                AsyncMock(return_value="token"),
            ):
                book_res = await async_client.post(
                    f"{base}/participants/{participant_user_id}/book",
                    json={"barcode": "CAMP89001", "sync_collection_to_now": True},
                    headers=headers,
                )

    assert book_res.status_code == 200
    assert book_res.json()["data"]["booking_id"] == "1715890001"

    blood_row = await get_current_blood_booking(
        test_db_session, engagement_participant_id=engagement_participant_id
    )
    assert blood_row is not None
    assert blood_row.barcode == "CAMP89001"
    assert blood_row.booking_id == "1715890001"
    assert blood_row.collected_at is not None
