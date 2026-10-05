"""Integration tests for expert portal dashboard."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from modules.engagements.enums import ConsultationMode
from modules.engagements.models import Engagement, EngagementParticipant, OnboardingAssistantAssignment
from modules.experts.consultations import consultation_dashboard_status
from modules.experts.models import ConsultationBooking, Expert
from modules.organizations.models import Organization
from modules.users.models import User
from tests.helpers.auth import employee_auth_header, partner_auth_header, seed_employee, seed_partner


def test_consultation_dashboard_status_rules():
    now = datetime(2026, 10, 5, 10, 15)
    assert (
        consultation_dashboard_status(
            done=True,
            date_str="2026-10-05",
            slot_str="09:00",
            session_duration_mins=30,
            now=now,
        )
        == "completed"
    )
    assert (
        consultation_dashboard_status(
            done=False,
            date_str="2026-10-05",
            slot_str="10:00",
            session_duration_mins=30,
            now=now,
        )
        == "live_now"
    )
    assert (
        consultation_dashboard_status(
            done=False,
            date_str="2026-10-05",
            slot_str="11:00",
            session_duration_mins=30,
            now=now,
        )
        == "upcoming"
    )
    assert (
        consultation_dashboard_status(
            done=False,
            date_str="2026-10-05",
            slot_str="09:00",
            session_duration_mins=30,
            now=now,
        )
        == "upcoming"
    )


async def _seed_dashboard_data(test_db_session) -> int:
    expert_partner_id = 78581
    other_partner_id = 78582
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    now = datetime.now()
    live_slot = now.strftime("%H:%M")

    test_db_session.add(
        Organization(
            organization_id=7858,
            name="Dash Org",
            organization_type="corporate",
            status="active",
        )
    )
    users = [
        User(
            user_id=78591 + i,
            age=30,
            phone=f"78591{i:06d}"[:15],
            email=f"dash.user{i}@test.example",
            first_name=["John", "Live", "Future", "Priya", "Camp", "Week"][i],
            last_name=["Doe", "Now", "Slot", "Sharma", "Patient", "Extra"][i],
            status="active",
        )
        for i in range(6)
    ]
    test_db_session.add_all(users)
    await test_db_session.flush()
    partner = await seed_partner(
        test_db_session,
        partner_id=expert_partner_id,
        role="expert",
        name="Sandeep Expert",
        phone=f"785{expert_partner_id:07d}"[:15],
        email=f"expert{expert_partner_id}@test.example",
        commit=False,
    )
    expert_partner_id = partner.partner_id
    other_partner = await seed_partner(
        test_db_session,
        partner_id=other_partner_id,
        role="expert",
        name="Other Expert",
        phone=f"785{other_partner_id:07d}"[:15],
        email=f"expert{other_partner_id}@test.example",
        commit=False,
    )
    other_partner_id = other_partner.partner_id
    expert = Expert(
        partner_id=expert_partner_id,
        expert_type="nutritionist",
        specialization="Nutrition",
        status="active",
        session_duration_mins=30,
    )
    other_expert = Expert(
        partner_id=other_partner_id,
        expert_type="doctor",
        specialization="GP",
        status="active",
        session_duration_mins=30,
    )
    test_db_session.add_all([expert, other_expert])
    await test_db_session.flush()
    assert (partner.status or "").lower() == "active"
    assert str(getattr(partner.role, "value", partner.role)) == "expert"

    test_db_session.add(
        Engagement(
            engagement_id=88701,
            engagement_name="NVIDIA Health Camp",
            engagement_code="DASH88701",
            engagement_type=1,
            consultations={"nutritionist": True, "doctor": True},
            consultation_mode=ConsultationMode.online,
            assessment_package_id=1,
            diagnostic_package_id=1,
            city="BLR",
            slot_duration=30,
            start_date=today,
            end_date=today + timedelta(days=7),
            status="running",
        )
    )
    test_db_session.add(
        Engagement(
            engagement_id=88702,
            engagement_name="ABC Wellness Camp",
            engagement_code="DASH88702",
            engagement_type=1,
            organization_id=7858,
            camp_no=785801,
            consultations={"nutritionist": True},
            consultation_mode=ConsultationMode.offline,
            assessment_package_id=1,
            diagnostic_package_id=1,
            city="BLR",
            slot_duration=20,
            start_date=today,
            end_date=today + timedelta(days=1),
            status="running",
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        OnboardingAssistantAssignment(
            onboarding_assistant_id=785801,
            partner_id=expert_partner_id,
            engagement_id=88702,
        )
    )

    participant_specs = [
        (78521, 88701, 78591, 887101),
        (78522, 88701, 78592, 887102),
        (78523, 88701, 78593, 887103),
        (78524, 88701, 78594, 887105),
        (78525, 88702, 78595, 887106),
        (78526, 88701, 78596, 887107),
    ]
    test_db_session.add_all(
        [
            EngagementParticipant(
                engagement_participant_id=pid,
                engagement_id=eid,
                user_id=uid,
                booked_by_user_id=uid,
                consultation_booking_ids=[cid],
            )
            for pid, eid, uid, cid in participant_specs
        ]
    )
    await test_db_session.flush()

    extra_date = week_start if week_start != today else today
    extra_slot = "07:00" if week_start != today else "07:30"
    extra_done = True

    test_db_session.add_all(
        [
            ConsultationBooking(
                consultation_id=887101,
                engagement_participant_id=78521,
                expert_type="nutritionist",
                expert_id=expert.expert_id,
                want=True,
                consultation_date=today,
                consultation_slot="08:00",
                done=True,
                meet_link="https://meet.example/done",
            ),
            ConsultationBooking(
                consultation_id=887102,
                engagement_participant_id=78522,
                expert_type="nutritionist",
                expert_id=expert.expert_id,
                want=True,
                consultation_date=today,
                consultation_slot=live_slot,
                done=False,
                meet_link="https://meet.example/live",
            ),
            ConsultationBooking(
                consultation_id=887103,
                engagement_participant_id=78523,
                expert_type="nutritionist",
                expert_id=expert.expert_id,
                want=True,
                consultation_date=today,
                consultation_slot="23:59",
                done=False,
                meet_link="https://meet.example/upcoming",
            ),
            ConsultationBooking(
                consultation_id=887104,
                engagement_participant_id=78521,
                expert_type="doctor",
                expert_id=other_expert.expert_id,
                want=True,
                consultation_date=today,
                consultation_slot="12:00",
                done=False,
            ),
            ConsultationBooking(
                consultation_id=887105,
                engagement_participant_id=78524,
                expert_type="nutritionist",
                want=True,
                consultation_date=today,
                consultation_slot="15:00",
                done=False,
                created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            ),
            ConsultationBooking(
                consultation_id=887106,
                engagement_participant_id=78525,
                expert_type="nutritionist",
                want=True,
                consultation_date=today,
                consultation_slot="11:30",
                consultation_cabin="C1",
                done=False,
            ),
            ConsultationBooking(
                consultation_id=887107,
                engagement_participant_id=78526,
                expert_type="nutritionist",
                expert_id=expert.expert_id,
                want=True,
                consultation_date=extra_date,
                consultation_slot=extra_slot,
                done=extra_done,
            ),
        ]
    )
    await test_db_session.commit()
    return expert_partner_id


@pytest.mark.asyncio
async def test_portal_dashboard_scoped_to_logged_in_expert(async_client, test_db_session):
    partner_id = await _seed_dashboard_data(test_db_session)
    headers = partner_auth_header(partner_id)

    response = await async_client.get(
        "/experts/portal/dashboard",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    assert data["summary"]["requests_waiting"] == 1
    assert data["summary"]["consultations_today"] >= 3
    assert data["summary"]["consultations_today_completed"] >= 1
    assert data["summary"]["open_camps"] == 1
    assert data["summary"]["hours_this_week"] > 0

    today_ids = {item["consultation_id"] for item in data["todays_consultations"]}
    assert 887104 not in today_ids
    assert 887101 in today_ids
    completed = next(item for item in data["todays_consultations"] if item["consultation_id"] == 887101)
    assert completed["status"] == "completed"
    assert completed["engagement_name"] == "NVIDIA Health Camp"
    assert completed["mode"] == "online"

    upcoming = next(item for item in data["todays_consultations"] if item["consultation_id"] == 887103)
    assert upcoming["status"] == "upcoming"
    assert upcoming["meet_link"] == "https://meet.example/upcoming"

    live = next(item for item in data["todays_consultations"] if item["consultation_id"] == 887102)
    assert live["status"] == "live_now"

    assert len(data["requests_waiting"]) == 1
    request = data["requests_waiting"][0]
    assert request["first_name"] == "Priya"
    assert request["engagement_name"] == "NVIDIA Health Camp"
    assert request["waiting_minutes"] >= 9
    assert request["created_at"]

    assert len(data["open_camps"]) == 1
    camp = data["open_camps"][0]
    assert camp["engagement_name"] == "ABC Wellness Camp"
    assert camp["consultation_pending_count"] == 1
    assert camp["next_consultation_slot"] == "11:30"

    weekly = data["weekly_hours"]
    assert weekly["session_duration_mins"] == 30
    assert weekly["completed_count"] >= 1
    assert len(weekly["days"]) == 7
    assert weekly["days"][0]["weekday"] == "Monday"


@pytest.mark.asyncio
async def test_portal_dashboard_empty_for_admin_without_expert(async_client, test_db_session):
    await _seed_dashboard_data(test_db_session)
    await seed_employee(
        test_db_session,
        employee_id=88790,
        role="admin",
        name="Admin User",
        phone="887000000090",
        email="admin.dash@example.com",
    )

    response = await async_client.get(
        "/experts/portal/dashboard",
        headers=employee_auth_header(88790),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["summary"]["requests_waiting"] == 0
    assert data["summary"]["consultations_today"] == 0
    assert data["summary"]["open_camps"] == 0
    assert data["summary"]["hours_this_week"] == 0.0
    assert data["todays_consultations"] == []
    assert data["requests_waiting"] == []
    assert data["open_camps"] == []
    assert data["weekly_hours"]["completed_count"] == 0
    assert len(data["weekly_hours"]["days"]) == 7
