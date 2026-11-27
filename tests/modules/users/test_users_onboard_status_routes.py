"""Tests for public GET /users/onboard/status."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text

from common.masking import mask_email, mask_phone
from modules.assessments.models import (
    AssessmentCategoryProgress,
    AssessmentInstance,
    AssessmentPackageCategory,
)
from modules.engagements.models import CampUserOnboardingPayloadField, Engagement, EngagementParticipant
from modules.questionnaire.models import QuestionnaireCategory, QuestionnaireDefinition, QuestionnaireResponse
from modules.users.models import User
from tests.helpers.engagement_types import engagement_type_id


def _camp_code(seed: int) -> str:
    return f"OB{seed:010d}"[:12]


def _url(**params: str) -> str:
    parts = [f"{key}={value}" for key, value in params.items()]
    return "/users/onboard/status?" + "&".join(parts)


async def _seed_core_packages(session) -> None:
    await session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, status) "
            "VALUES (1, 'PK1', 'Package', 1) ON CONFLICT (package_id) DO NOTHING"
        )
    )
    await session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, reference_id, package_name, diagnostic_provider, status, bookings_count, external_package_code) "
            "VALUES (1, 'REF1', 'Diag Package', 'orange_health', 1, 0, 'PKG1') "
            "ON CONFLICT (diagnostic_package_id) DO NOTHING"
        )
    )


async def _seed_engagement_bundle(
    session,
    *,
    seed: int,
    user: User | None = None,
    onboard: bool = False,
    camp_no: int | None = None,
    employee_id: str | None = None,
    engagement_code: str | None = None,
) -> tuple[Engagement, str | None]:
    eng_id = 900_000 + seed
    org_id = 900_000 + seed
    camp = camp_no if camp_no is not None else 9_000_000_000 + seed
    code = engagement_code or f"EN{seed:08d}"

    await _seed_core_packages(session)
    type_id = await engagement_type_id(session, "bio_ai")
    await session.execute(
        text(
            "INSERT INTO organizations (organization_id, name, status, departments) "
            "VALUES (:oid, :name, 1, '[]'::json) ON CONFLICT (organization_id) DO NOTHING"
        ),
        {"oid": org_id, "name": f"Org {org_id}"},
    )

    engagement = await session.get(Engagement, eng_id)
    if engagement is None:
        await session.execute(
            text(
                "INSERT INTO engagements ("
                "engagement_id, engagement_name, organization_id, camp_no, engagement_code, engagement_type, "
                "assessment_package_id, diagnostic_package_id, city, slot_duration, start_date, end_date, status"
                ") VALUES ("
                ":eid, :ename, :oid, :camp, :code, :etype, 1, 1, 'Pune', 30, '2026-01-01', '2026-12-31', 3"
                ") ON CONFLICT (engagement_id) DO NOTHING"
            ),
            {
                "eid": eng_id,
                "ename": f"Eng {seed}",
                "oid": org_id,
                "camp": camp,
                "code": code,
                "etype": type_id,
            },
        )

    camp_code = _camp_code(seed)
    camp_row = (
        await session.execute(
            select(CampUserOnboardingPayloadField).where(CampUserOnboardingPayloadField.camp_no == camp)
        )
    ).scalar_one_or_none()
    if camp_row is None:
        session.add(
            CampUserOnboardingPayloadField(
                camp_no=camp,
                camp_code=camp_code,
                onboarding_payload={},
            )
        )

    await session.flush()

    if user is not None and onboard:
        existing = (
            await session.execute(
                select(EngagementParticipant).where(
                    EngagementParticipant.engagement_id == eng_id,
                    EngagementParticipant.user_id == user.user_id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                EngagementParticipant(
                    engagement_id=eng_id,
                    user_id=user.user_id,
                    booked_by_user_id=user.user_id,
                    participants_employee_id=employee_id,
                    participant_department="Engineering",
                    participant_blood_group="O+",
                )
            )
    await session.flush()
    eng = await session.get(Engagement, eng_id)
    assert eng is not None
    return eng, camp_code


@pytest.mark.asyncio
async def test_onboard_status_requires_phone_or_email(async_client):
    response = await async_client.get(_url(camp_code=_camp_code(1), engagement_code="EN00000001"))
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_onboard_status_requires_camp_or_engagement(async_client):
    response = await async_client.get(_url(phone="9876543210"))
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_onboard_status_unknown_engagement_code(async_client, test_db_session):
    test_db_session.add(User(user_id=98101, phone="9810100000", email="a@example.com", status="active", age=30))
    await test_db_session.commit()
    response = await async_client.get(_url(phone="9810100000", engagement_code="NOENG98101"))
    assert response.status_code == 404
    assert response.json()["error_code"] == "ENGAGEMENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_onboard_status_unknown_camp_code(async_client, test_db_session):
    test_db_session.add(User(user_id=98102, phone="9810200000", status="active", age=30))
    await test_db_session.commit()
    response = await async_client.get(_url(phone="9810200000", camp_code="UNKNOWNCAMP1"))
    assert response.status_code == 404
    assert response.json()["error_code"] == "CAMP_NOT_FOUND"


@pytest.mark.asyncio
async def test_onboard_status_engagement_not_in_camp(async_client, test_db_session):
    user = User(user_id=98103, phone="9810300000", status="active", age=30)
    test_db_session.add(user)
    await test_db_session.flush()
    eng_a, camp_a = await _seed_engagement_bundle(test_db_session, seed=98103, user=user)
    eng_b, _ = await _seed_engagement_bundle(
        test_db_session,
        seed=98104,
        camp_no=int(eng_a.camp_no or 0) + 1,
        engagement_code="EN0098104",
    )
    await test_db_session.commit()

    response = await async_client.get(
        _url(phone="9810300000", camp_code=camp_a or "", engagement_code=eng_b.engagement_code)
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_onboard_status_no_match_returns_empty(async_client, test_db_session):
    user = User(user_id=98105, phone="9810500000", status="active", age=30)
    test_db_session.add(user)
    _eng, camp_code = await _seed_engagement_bundle(test_db_session, seed=98105)
    await test_db_session.commit()

    response = await async_client.get(_url(phone="9000000000", camp_code=camp_code or ""))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["profiles"] == []
    assert data["onboarding_status"] == []
    assert data["questionnaire_status"] == []


@pytest.mark.asyncio
async def test_onboard_status_public_masks_and_no_auth(async_client, test_db_session):
    user = User(
        user_id=98106,
        phone="9810600000",
        email="Status.User@Example.COM",
        first_name="Status",
        last_name="User",
        status="active",
        age=30,
    )
    test_db_session.add(user)
    await test_db_session.flush()
    _eng, camp_code = await _seed_engagement_bundle(
        test_db_session, seed=98106, user=user, onboard=True, employee_id="E98106"
    )
    await test_db_session.commit()

    response = await async_client.get(_url(phone="9810600000", camp_code=camp_code or ""))
    assert response.status_code == 200
    profile = response.json()["data"]["profiles"][0]
    assert profile["phone"] == mask_phone(user.phone)
    assert profile["email"] == mask_email(user.email)
    assert profile["employee_id"] == "E98106"
    assert response.json()["data"]["onboarding_status"][0]["is_participant"] is True
    assert response.json()["data"]["questionnaire_status"][0]["status"] == "NOT_STARTED"


@pytest.mark.asyncio
async def test_onboard_status_phone_sub_profiles_primary_first(async_client, test_db_session):
    primary = User(
        user_id=98107,
        phone="+919810700007",
        email="primary98107@example.com",
        first_name="Primary",
        status="active",
        age=40,
    )
    sub = User(
        user_id=98108,
        parent_id=98107,
        phone="+919810700007",
        email="sub98108@example.com",
        first_name="Sub",
        status="active",
        age=12,
    )
    test_db_session.add_all([primary, sub])
    await test_db_session.flush()
    _eng, camp_code = await _seed_engagement_bundle(test_db_session, seed=98107, user=primary, onboard=True)
    await test_db_session.commit()

    response = await async_client.get(_url(phone="+919810700007", camp_code=camp_code or ""))
    assert response.status_code == 200
    ids = [row["user_id"] for row in response.json()["data"]["profiles"]]
    assert ids == [98107, 98108]


@pytest.mark.asyncio
async def test_onboard_status_email_only_case_insensitive(async_client, test_db_session):
    user = User(user_id=98109, phone="9810900000", email="MixedCase98109@Example.COM", status="active", age=28)
    test_db_session.add(user)
    await test_db_session.flush()
    _eng, camp_code = await _seed_engagement_bundle(test_db_session, seed=98109, user=user, onboard=False)
    await test_db_session.commit()

    response = await async_client.get(
        _url(email="  mixedcase98109@example.com  ", camp_code=camp_code or "")
    )
    assert response.status_code == 200
    assert len(response.json()["data"]["profiles"]) == 1
    assert response.json()["data"]["profiles"][0]["user_id"] == 98109


@pytest.mark.asyncio
async def test_onboard_status_not_onboarded_questionnaire_null(async_client, test_db_session):
    user = User(user_id=98110, phone="9811000000", status="active", age=30)
    test_db_session.add(user)
    await test_db_session.flush()
    _eng, camp_code = await _seed_engagement_bundle(test_db_session, seed=98110, user=user, onboard=False)
    await test_db_session.commit()

    response = await async_client.get(_url(phone="9811000000", engagement_code=_eng.engagement_code))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["onboarding_status"][0]["is_participant"] is False
    assert data["questionnaire_status"][0]["status"] is None


@pytest.mark.asyncio
async def test_onboard_status_past_participant_fallback(async_client, test_db_session):
    user = User(user_id=98111, phone="9811100000", status="active", age=33)
    test_db_session.add(user)
    await test_db_session.flush()
    past_eng, _ = await _seed_engagement_bundle(
        test_db_session,
        seed=98111,
        user=user,
        onboard=True,
        employee_id="PAST98111",
    )
    # Separate scoped engagement where user is not enrolled
    scoped_eng, camp_code = await _seed_engagement_bundle(
        test_db_session,
        seed=98112,
        camp_no=int(past_eng.camp_no or 0) + 99,
        engagement_code="EN0098112",
        user=None,
        onboard=False,
    )
    await test_db_session.commit()

    response = await async_client.get(_url(phone="9811100000", engagement_code=scoped_eng.engagement_code))
    assert response.status_code == 200
    profile = response.json()["data"]["profiles"][0]
    assert profile["employee_id"] == "PAST98111"
    assert profile["department"] == "Engineering"
    assert response.json()["data"]["onboarding_status"][0]["is_participant"] is False


@pytest.mark.asyncio
async def test_onboard_status_questionnaire_completed(async_client, test_db_session):
    user = User(user_id=98113, phone="9811300000", status="active", age=30)
    test_db_session.add(user)
    await test_db_session.flush()
    eng, camp_code = await _seed_engagement_bundle(
        test_db_session, seed=98113, user=user, onboard=True, employee_id="E98113"
    )
    pkg_id = int(eng.assessment_package_id or 1)
    cat_id = 900_000 + 98113
    if await test_db_session.get(QuestionnaireCategory, cat_id) is None:
        test_db_session.add(
            QuestionnaireCategory(category_id=cat_id, category_key="cat_os", display_name="Cat", status="active")
        )
    await test_db_session.flush()
    test_db_session.add(AssessmentPackageCategory(package_id=pkg_id, category_id=cat_id, display_order=1))
    inst = AssessmentInstance(
        user_id=user.user_id,
        package_id=pkg_id,
        engagement_id=eng.engagement_id,
        status="completed",
        assigned_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    test_db_session.add(inst)
    await test_db_session.flush()
    test_db_session.add(
        AssessmentCategoryProgress(
            assessment_instance_id=inst.assessment_instance_id,
            category_id=cat_id,
            status="complete",
            is_submitted=True,
        )
    )
    await test_db_session.commit()

    response = await async_client.get(_url(phone="9811300000", camp_code=camp_code or ""))
    assert response.status_code == 200
    assert response.json()["data"]["questionnaire_status"][0]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_onboard_status_questionnaire_in_progress(async_client, test_db_session):
    user = User(user_id=98114, phone="9811400000", status="active", age=30)
    test_db_session.add(user)
    await test_db_session.flush()
    eng, camp_code = await _seed_engagement_bundle(test_db_session, seed=98114, user=user, onboard=True)
    pkg_id = int(eng.assessment_package_id or 1)
    cat_id = 900_000 + 98114
    test_db_session.add(
        QuestionnaireCategory(category_id=cat_id, category_key="cat_os2", display_name="Cat2", status="active")
    )
    await test_db_session.flush()
    test_db_session.add(AssessmentPackageCategory(package_id=pkg_id, category_id=cat_id, display_order=1))
    inst = AssessmentInstance(
        user_id=user.user_id,
        package_id=pkg_id,
        engagement_id=eng.engagement_id,
        status="active",
        assigned_at=datetime.now(timezone.utc),
    )
    test_db_session.add(inst)
    await test_db_session.flush()
    q_id = 900_000 + 98114
    test_db_session.add(
        QuestionnaireDefinition(
            question_id=q_id,
            question_key="q_os_in_prog",
            question_text="Q",
            question_type="text",
            status="active",
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        QuestionnaireResponse(
            assessment_instance_id=inst.assessment_instance_id,
            question_id=q_id,
            category_ids=[cat_id],
            answer={"v": "draft"},
            is_carried_forward=False,
        )
    )
    await test_db_session.commit()

    response = await async_client.get(_url(phone="9811400000", engagement_code=eng.engagement_code))
    assert response.status_code == 200
    assert response.json()["data"]["questionnaire_status"][0]["status"] == "IN_PROGRESS"


@pytest.mark.asyncio
async def test_onboard_status_carried_forward_only_not_started(async_client, test_db_session):
    user = User(user_id=98115, phone="9811500000", status="active", age=30)
    test_db_session.add(user)
    await test_db_session.flush()
    eng, camp_code = await _seed_engagement_bundle(test_db_session, seed=98115, user=user, onboard=True)
    pkg_id = int(eng.assessment_package_id or 1)
    inst = AssessmentInstance(
        user_id=user.user_id,
        package_id=pkg_id,
        engagement_id=eng.engagement_id,
        status="active",
        assigned_at=datetime.now(timezone.utc),
    )
    test_db_session.add(inst)
    await test_db_session.flush()
    q_id = 900_000 + 98115
    cat_id = 900_000 + 98115
    test_db_session.add(
        QuestionnaireDefinition(
            question_id=q_id,
            question_key="q_os_cf",
            question_text="Q",
            question_type="text",
            status="active",
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        QuestionnaireResponse(
            assessment_instance_id=inst.assessment_instance_id,
            question_id=q_id,
            category_ids=[cat_id],
            answer={"v": "old"},
            is_carried_forward=True,
        )
    )
    await test_db_session.commit()

    response = await async_client.get(_url(phone="9811500000", camp_code=camp_code or ""))
    assert response.status_code == 200
    assert response.json()["data"]["questionnaire_status"][0]["status"] == "NOT_STARTED"


@pytest.mark.asyncio
async def test_onboard_status_camp_scope_multiple_engagements(async_client, test_db_session):
    user = User(user_id=98116, phone="9811600000", status="active", age=30)
    test_db_session.add(user)
    await test_db_session.flush()
    camp_no = 9_811_600_000
    eng1, camp_code = await _seed_engagement_bundle(
        test_db_session, seed=98116, user=user, onboard=True, camp_no=camp_no, engagement_code="EN0098116A"
    )
    await _seed_engagement_bundle(
        test_db_session,
        seed=98117,
        camp_no=camp_no,
        engagement_code="EN0098116B",
        user=None,
        onboard=False,
    )
    await test_db_session.commit()

    response = await async_client.get(_url(phone="9811600000", camp_code=camp_code or ""))
    assert response.status_code == 200
    assert response.json()["data"]["onboarding_status"][0]["is_participant"] is True


@pytest.mark.asyncio
async def test_onboard_status_rate_limited(async_client, test_db_session):
    user = User(user_id=98118, phone="9811800000", status="active", age=30)
    test_db_session.add(user)
    await test_db_session.flush()
    _eng, camp_code = await _seed_engagement_bundle(test_db_session, seed=98118, user=user)
    await test_db_session.commit()

    url = _url(phone="9811800000", camp_code=camp_code or "")
    last_status = 200
    for _ in range(11):
        last_status = (await async_client.get(url)).status_code
    assert last_status == 429