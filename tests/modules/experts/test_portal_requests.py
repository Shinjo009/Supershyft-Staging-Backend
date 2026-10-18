"""Integration tests for expert portal pending consultation requests."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from modules.engagements.enums import ConsultationMode
from modules.engagements.models import Engagement, EngagementParticipant, OnboardingAssistantAssignment
from modules.experts.models import ConsultationBooking, Expert
from modules.users.models import User
from tests.helpers.auth import employee_auth_header, partner_auth_header, seed_employee, seed_partner


async def _seed_online_pending_request_fixture(test_db_session) -> dict:
    """Doctor OA on eng A; nutritionist request on A; doctor request on B (doctor not OA on B)."""
    doctor_partner = await seed_partner(
        test_db_session,
        partner_id=78610,
        role="expert",
        phone="786100000010",
        email="doctor78610@test.example",
        commit=False,
    )
    other_doctor_partner = await seed_partner(
        test_db_session,
        partner_id=78611,
        role="expert",
        phone="786100000011",
        email="doctor78611@test.example",
        commit=False,
    )
    doctor = Expert(
        partner_id=doctor_partner.partner_id,
        expert_type="doctor",
        specialization="GP",
        status="active",
    )
    other_doctor = Expert(
        partner_id=other_doctor_partner.partner_id,
        expert_type="doctor",
        specialization="GP",
        status="active",
    )
    test_db_session.add_all([doctor, other_doctor])
    await test_db_session.flush()

    today = date.today()
    eng_a = 78620
    eng_b = 78621
    test_db_session.add_all(
        [
            Engagement(
                engagement_id=eng_a,
                engagement_name="Eng A",
                engagement_code="PRE78620",
                engagement_type=1,
                consultations={"doctor": True, "nutritionist": True},
                consultation_mode=ConsultationMode.online,
                assessment_package_id=1,
                diagnostic_package_id=1,
                city="BLR",
                slot_duration=20,
                start_date=today,
                end_date=today + timedelta(days=7),
                status="running",
            ),
            Engagement(
                engagement_id=eng_b,
                engagement_name="Eng B",
                engagement_code="PRE78621",
                engagement_type=1,
                consultations={"doctor": True},
                consultation_mode=ConsultationMode.online,
                assessment_package_id=1,
                diagnostic_package_id=1,
                city="BLR",
                slot_duration=20,
                start_date=today,
                end_date=today + timedelta(days=7),
                status="running",
            ),
        ]
    )
    await test_db_session.flush()

    test_db_session.add(
        OnboardingAssistantAssignment(
            onboarding_assistant_id=786201,
            partner_id=doctor_partner.partner_id,
            engagement_id=eng_a,
        )
    )

    user_n = User(
        user_id=78630,
        age=30,
        phone="786300000030",
        first_name="Nutri",
        last_name="Patient",
        status="active",
    )
    user_d = User(
        user_id=78631,
        age=31,
        phone="786300000031",
        first_name="Doc",
        last_name="Patient",
        status="active",
    )
    test_db_session.add_all([user_n, user_d])
    await test_db_session.flush()

    part_n = 78640
    part_d = 78641
    cid_n = 78650
    cid_d = 78651
    test_db_session.add_all(
        [
            EngagementParticipant(
                engagement_participant_id=part_n,
                engagement_id=eng_a,
                user_id=user_n.user_id,
                booked_by_user_id=user_n.user_id,
                consultation_booking_ids=[cid_n],
            ),
            EngagementParticipant(
                engagement_participant_id=part_d,
                engagement_id=eng_b,
                user_id=user_d.user_id,
                booked_by_user_id=user_d.user_id,
                consultation_booking_ids=[cid_d],
            ),
        ]
    )
    await test_db_session.flush()

    test_db_session.add_all(
        [
            ConsultationBooking(
                consultation_id=cid_n,
                engagement_participant_id=part_n,
                expert_type="nutritionist",
                want=True,
                consultation_date=today,
                consultation_slot="10:00",
            ),
            ConsultationBooking(
                consultation_id=cid_d,
                engagement_participant_id=part_d,
                expert_type="doctor",
                want=True,
                consultation_date=today,
                consultation_slot="11:00",
            ),
        ]
    )
    await test_db_session.commit()

    return {
        "doctor_partner_id": doctor_partner.partner_id,
        "eng_a": eng_a,
        "eng_b": eng_b,
        "user_n": user_n.user_id,
        "user_d": user_d.user_id,
        "cid_n": cid_n,
        "cid_d": cid_d,
    }


@pytest.mark.asyncio
async def test_portal_requests_filters_by_expert_type_and_oa(async_client, test_db_session):
    fx = await _seed_online_pending_request_fixture(test_db_session)

    response = await async_client.get(
        "/experts/portal/requests",
        headers=partner_auth_header(fx["doctor_partner_id"]),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    consultation_ids = {row["consultation_id"] for row in data}
    assert fx["cid_n"] not in consultation_ids
    assert consultation_ids == set()


@pytest.mark.asyncio
async def test_portal_requests_admin_sees_all_pending(async_client, test_db_session):
    fx = await _seed_online_pending_request_fixture(test_db_session)
    await seed_employee(
        test_db_session,
        employee_id=78699,
        role="admin",
        phone="786990000099",
        email="admin78699@test.example",
    )

    response = await async_client.get(
        "/experts/portal/requests",
        headers=employee_auth_header(78699),
    )
    assert response.status_code == 200
    consultation_ids = {row["consultation_id"] for row in response.json()["data"]}
    assert fx["cid_n"] in consultation_ids
    assert fx["cid_d"] in consultation_ids


@pytest.mark.asyncio
async def test_portal_confirm_requires_oa_assignment(async_client, test_db_session):
    fx = await _seed_online_pending_request_fixture(test_db_session)

    response = await async_client.post(
        "/experts/portal/confirm",
        headers=partner_auth_header(fx["doctor_partner_id"]),
        json={
            "user_id": fx["user_d"],
            "engagement_id": fx["eng_b"],
            "expert_type": "doctor",
            "date": date.today().isoformat(),
            "slot": "11:00",
        },
    )
    assert response.status_code == 403
    assert "not assigned" in response.json()["message"].lower()
