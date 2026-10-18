"""Integration tests for engagement feedback routes."""

from __future__ import annotations

from datetime import date

import pytest

from modules.engagements.models import Engagement, EngagementParticipant
from modules.users.models import User
from tests.helpers.auth import employee_auth_header, user_auth_header
from tests.modules.engagements.test_engagements_routes import (
    _engagement_type_id,
    _seed_assessment_package,
    _seed_diagnostic_package,
    _seed_employee,
    _seed_organization,
)


async def _seed_feedback_fixture(
    test_db_session,
    *,
    engagement_id: int = 88001,
    engagement_code: str = "FB88001",
    user_id: int = 88001,
    employee_id: int = 880,
    engagement_type_code: str = "bio_ai_with_consultation",
) -> None:
    await _seed_employee(test_db_session, employee_id=employee_id)
    await _seed_organization(test_db_session, organization_id=880, name="Feedback Org")
    await _seed_assessment_package(test_db_session, package_id=880, package_code="PKG880")
    await _seed_diagnostic_package(test_db_session, diagnostic_package_id=880)
    type_id = await _engagement_type_id(test_db_session, engagement_type_code)

    test_db_session.add(
        User(
            user_id=user_id,
            age=30,
            phone="8800100001",
            status="active",
            first_name="Feedback",
            last_name="User",
        )
    )
    await test_db_session.flush()

    test_db_session.add(
        Engagement(
            engagement_id=engagement_id,
            engagement_name="Feedback Camp",
            engagement_code=engagement_code,
            organization_id=880,
            engagement_type=type_id,
            assessment_package_id=880,
            diagnostic_package_id=880,
            city="BLR",
            slot_duration=20,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 2),
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
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_submit_engagement_feedback_happy_path(async_client, test_db_session):
    await _seed_feedback_fixture(test_db_session)
    response = await async_client.post(
        "/users/me/engagements/88001/feedback",
        headers=user_auth_header(88001),
        json={
            "overall_rating": "excellent",
            "category_ratings": {
                "blood_collection": 5,
                "bio_ai_reports": 4,
                "consultations": 5,
            },
            "comment": "Great experience",
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["engagement_id"] == 88001
    assert data["overall_rating"] == "excellent"
    assert data["category_ratings"]["blood_collection"] == 5
    assert data["comment"] == "Great experience"


@pytest.mark.asyncio
async def test_submit_engagement_feedback_duplicate_returns_409(async_client, test_db_session):
    await _seed_feedback_fixture(test_db_session)
    headers = user_auth_header(88001)
    payload = {
        "overall_rating": "good",
        "category_ratings": {"blood_collection": 3},
        "comment": None,
    }
    first = await async_client.post("/users/me/engagements/88001/feedback", headers=headers, json=payload)
    assert first.status_code == 201
    second = await async_client.post("/users/me/engagements/88001/feedback", headers=headers, json=payload)
    assert second.status_code == 409
    assert second.json()["error_code"] == "FEEDBACK_ALREADY_SUBMITTED"


@pytest.mark.asyncio
async def test_submit_engagement_feedback_not_enrolled_returns_404(async_client, test_db_session):
    await _seed_feedback_fixture(test_db_session)
    test_db_session.add(User(user_id=88002, age=30, phone="8800200001", status="active"))
    await test_db_session.commit()

    response = await async_client.post(
        "/users/me/engagements/88001/feedback",
        headers=user_auth_header(88002),
        json={"overall_rating": "good", "category_ratings": {}},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "PARTICIPANT_NOT_FOUND"


@pytest.mark.asyncio
async def test_submit_engagement_feedback_invalid_category_returns_400(async_client, test_db_session):
    await _seed_feedback_fixture(test_db_session, engagement_type_code="consultation")
    response = await async_client.post(
        "/users/me/engagements/88001/feedback",
        headers=user_auth_header(88001),
        json={
            "overall_rating": "good",
            "category_ratings": {"blood_collection": 5},
        },
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_pending_engagement_feedback(async_client, test_db_session):
    await _seed_feedback_fixture(test_db_session)
    pending = await async_client.get(
        "/users/me/engagement-feedback/pending",
        headers=user_auth_header(88001),
    )
    assert pending.status_code == 200
    body = pending.json()["data"]
    assert body["pending"] is True
    assert body["engagement_id"] == 88001
    assert body["engagement_code"] == "FB88001"
    assert "engagement_name" not in body
    assert "consultations" in body["category_keys"]

    await async_client.post(
        "/users/me/engagements/88001/feedback",
        headers=user_auth_header(88001),
        json={"overall_rating": "very_good", "category_ratings": {"consultations": 4}},
    )
    pending_after = await async_client.get(
        "/users/me/engagement-feedback/pending",
        headers=user_auth_header(88001),
    )
    assert pending_after.json()["data"]["pending"] is False


@pytest.mark.asyncio
async def test_admin_list_engagement_feedback(async_client, test_db_session):
    await _seed_feedback_fixture(test_db_session, employee_id=880)
    await async_client.post(
        "/users/me/engagements/88001/feedback",
        headers=user_auth_header(88001),
        json={
            "overall_rating": "could_be_better",
            "category_ratings": {"blood_collection": 2, "bio_ai_reports": 3, "consultations": 2},
            "comment": "Needs improvement",
        },
    )

    response = await async_client.get(
        "/engagements/88001/feedback",
        headers=employee_auth_header(880),
    )
    assert response.status_code == 200, response.text
    rows = response.json()["data"]
    assert response.json()["meta"]["total"] == 1
    assert len(rows) == 1
    assert rows[0]["overall_rating"] == "could_be_better"
    assert rows[0]["first_name"] == "Feedback"
    assert "Needs improvement" in (rows[0]["comment"] or "")
