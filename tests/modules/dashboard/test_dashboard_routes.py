"""Dashboard overview and employee /me pending_task_count."""

from __future__ import annotations

import pytest

from tests.helpers.auth import seed_employee, employee_auth_header


@pytest.mark.asyncio
async def test_dashboard_overview_returns_kpis(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8802, role="admin")
    response = await async_client.get(
        "/admin/dashboard/overview",
        headers=employee_auth_header(8802),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert "users" in data
    assert "year_stats" in data
    assert "payment_status_totals" in data
    assert "engagement_participants_total" in data
    assert "operations" not in data


@pytest.mark.asyncio
async def test_dashboard_operations_returns_ops_block(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8804, role="admin")
    response = await async_client.get(
        "/admin/dashboard/operations",
        headers=employee_auth_header(8804),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    ops = data["operations"]
    assert "engagements" in ops
    assert "participant_issues" in ops
    assert "pending_payments" in ops
    assert "failed_notifications" in ops
    assert "tickets" in ops
    assert "serviceability_issues" in ops


@pytest.mark.asyncio
async def test_employee_me_includes_pending_task_count(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8803, role="admin")
    response = await async_client.get(
        "/employees/auth/me",
        headers=employee_auth_header(8803),
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert "pending_task_count" in body
    assert isinstance(body["pending_task_count"], int)


@pytest.mark.asyncio
async def test_command_notification_health_shape(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8810, role="admin")
    response = await async_client.get(
        "/admin/dashboard/command/notification-health",
        params={"period": "all_time"},
        headers=employee_auth_header(8810),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data.keys()) >= {"sent", "failed", "pending", "total"}
    assert response.json()["meta"]["period"] == "all_time"


@pytest.mark.asyncio
async def test_command_people_registered_count_only(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8811, role="admin")
    response = await async_client.get(
        "/admin/dashboard/command/people-registered",
        params={"period": "all_time", "include_rows": "false"},
        headers=employee_auth_header(8811),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert "total" in body["meta"]
    assert isinstance(body["meta"]["total"], int)


@pytest.mark.asyncio
async def test_command_tests_completed_count_only(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8812, role="admin")
    response = await async_client.get(
        "/admin/dashboard/command/tests-completed",
        params={"period": "all_time", "include_rows": "false"},
        headers=employee_auth_header(8812),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    meta = body["meta"]
    assert meta["period"] == "all_time"
    for key in ("total", "b2b", "b2c"):
        assert key in meta
        assert isinstance(meta[key], int)
    assert meta["total"] == meta["b2b"] + meta["b2c"]


@pytest.mark.asyncio
async def test_command_questionnaire_pending_count_only(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8814, role="admin")
    response = await async_client.get(
        "/admin/dashboard/command/questionnaire-pending",
        params={"period": "all_time", "include_rows": "false"},
        headers=employee_auth_header(8814),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    meta = body["meta"]
    assert meta["period"] == "all_time"
    for key in ("total", "b2b", "b2c"):
        assert key in meta
        assert isinstance(meta[key], int)
    assert meta["total"] == meta["b2b"] + meta["b2c"]


@pytest.mark.asyncio
async def test_command_questionnaire_done_count_only(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8813, role="admin")
    response = await async_client.get(
        "/admin/dashboard/command/questionnaire-done",
        params={"period": "all_time", "include_rows": "false"},
        headers=employee_auth_header(8813),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    meta = body["meta"]
    assert meta["period"] == "all_time"
    for key in ("total", "b2b", "b2c"):
        assert key in meta
        assert isinstance(meta[key], int)
    assert meta["total"] == meta["b2b"] + meta["b2c"]


async def _seed_b2b_command_fixtures(test_db_session):
    """Seed B2B engagements across buckets + one B2C + null start_date row."""
    from datetime import date

    from modules.engagements.models import Engagement, EngagementParticipant
    from modules.organizations.models import Organization
    from modules.users.models import User

    org = Organization(
        organization_id=8820,
        name="B2B Command Org",
        organization_type="corporate",
        status="active",
    )
    test_db_session.add(org)
    await test_db_session.flush()

    today = date.today()
    fixtures = [
        # ongoing (running) with start_date = today
        dict(
            engagement_id=88201,
            engagement_code="B2B-ONG-88201",
            engagement_name="Ongoing Camp",
            organization_id=8820,
            city="Mumbai",
            start_date=today,
            end_date=today,
            status="running",
        ),
        # upcoming (scheduled)
        dict(
            engagement_id=88202,
            engagement_code="B2B-UP-88202",
            engagement_name="Upcoming Camp",
            organization_id=8820,
            city="Pune",
            start_date=today,
            end_date=today,
            status="scheduled",
        ),
        # completed
        dict(
            engagement_id=88203,
            engagement_code="B2B-DONE-88203",
            engagement_name="Completed Camp",
            organization_id=8820,
            city="Delhi",
            start_date=today,
            end_date=today,
            status="completed",
        ),
        # running but null start_date — only counted on all_time
        dict(
            engagement_id=88204,
            engagement_code="B2B-NULL-88204",
            engagement_name="Null Start Camp",
            organization_id=8820,
            city="Chennai",
            start_date=None,
            end_date=None,
            status="running",
        ),
        # B2C running — must never appear in B2B
        dict(
            engagement_id=88205,
            engagement_code="B2C-ONG-88205",
            engagement_name="B2C Camp",
            organization_id=None,
            city="Goa",
            start_date=today,
            end_date=today,
            status="running",
        ),
    ]
    for f in fixtures:
        test_db_session.add(Engagement(slot_duration=20, **f))
    await test_db_session.flush()

    user = User(
        user_id=88201,
        first_name="Pat",
        last_name="One",
        phone="8820100000",
        age=30,
        status="active",
    )
    test_db_session.add(user)
    await test_db_session.flush()
    test_db_session.add(
        EngagementParticipant(
            engagement_participant_id=88201,
            engagement_id=88201,
            user_id=88201,
            booked_by_user_id=88201,
        )
    )
    await test_db_session.commit()
    return today


@pytest.mark.asyncio
async def test_command_b2b_summary_buckets_and_all_time(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8820, role="admin")
    await _seed_b2b_command_fixtures(test_db_session)

    ranged = await async_client.get(
        "/admin/dashboard/command/b2b/summary",
        params={"period": "this_week"},
        headers=employee_auth_header(8820),
    )
    assert ranged.status_code == 200
    data = ranged.json()["data"]
    assert data["ongoing"] == 1  # null start_date excluded
    assert data["upcoming"] == 1
    assert data["completed"] == 1
    assert ranged.json()["meta"]["period"] == "this_week"

    all_time = await async_client.get(
        "/admin/dashboard/command/b2b/summary",
        params={"period": "all_time"},
        headers=employee_auth_header(8820),
    )
    assert all_time.status_code == 200
    all_data = all_time.json()["data"]
    assert all_data["ongoing"] == 2  # includes null start_date
    assert all_data["upcoming"] == 1
    assert all_data["completed"] == 1


@pytest.mark.asyncio
async def test_command_b2b_engagements_list_shape_and_participants(
    async_client, test_db_session
):
    await seed_employee(test_db_session, employee_id=8821, role="admin")
    await _seed_b2b_command_fixtures(test_db_session)

    response = await async_client.get(
        "/admin/dashboard/command/b2b/engagements",
        params={"bucket": "ongoing", "period": "this_week"},
        headers=employee_auth_header(8821),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["bucket"] == "ongoing"
    assert body["meta"]["total"] == 1
    row = body["data"][0]
    assert row["engagement_code"] == "B2B-ONG-88201"
    assert row["engagement_name"] == "Ongoing Camp"
    assert row["city"] == "Mumbai"
    assert row["status"] == "running"
    assert row["participant_count"] == 1
    assert "start_date" in row and "end_date" in row


@pytest.mark.asyncio
async def test_command_b2b_engagements_invalid_bucket(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8822, role="admin")
    response = await async_client.get(
        "/admin/dashboard/command/b2b/engagements",
        params={"bucket": "draft", "period": "all_time"},
        headers=employee_auth_header(8822),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_command_blood_report_generated_count_only(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8830, role="admin")
    response = await async_client.get(
        "/admin/dashboard/command/blood-report-generated",
        params={"period": "all_time", "include_rows": "false"},
        headers=employee_auth_header(8830),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    meta = body["meta"]
    for key in ("total", "b2b", "b2c"):
        assert key in meta
        assert isinstance(meta[key], int)
    assert meta["total"] == meta["b2b"] + meta["b2c"]


@pytest.mark.asyncio
async def test_command_bioai_report_generated_count_only(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8831, role="admin")
    response = await async_client.get(
        "/admin/dashboard/command/bioai-report-generated",
        params={"period": "all_time", "include_rows": "false"},
        headers=employee_auth_header(8831),
    )
    assert response.status_code == 200
    meta = response.json()["meta"]
    for key in ("total", "b2b", "b2c"):
        assert key in meta
    assert meta["total"] == meta["b2b"] + meta["b2c"]


@pytest.mark.asyncio
async def test_command_consultation_done_count_only(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8832, role="admin")
    response = await async_client.get(
        "/admin/dashboard/command/consultation-done",
        params={"period": "all_time", "include_rows": "false"},
        headers=employee_auth_header(8832),
    )
    assert response.status_code == 200
    meta = response.json()["meta"]
    for key in ("total", "b2b", "b2c"):
        assert key in meta
    assert meta["total"] == meta["b2b"] + meta["b2c"]


@pytest.mark.asyncio
async def test_command_open_engagements_and_null_start_date(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8833, role="admin")
    await _seed_b2b_command_fixtures(test_db_session)

    ranged = await async_client.get(
        "/admin/dashboard/command/open-engagements",
        params={"period": "this_week", "include_rows": "false"},
        headers=employee_auth_header(8833),
    )
    assert ranged.status_code == 200
    data = ranged.json()["meta"]
    # running+scheduled with non-null start: B2B ongoing, B2B upcoming, B2C running
    assert data["total"] == 3
    assert data["b2b"] == 2
    assert data["b2c"] == 1

    all_time = await async_client.get(
        "/admin/dashboard/command/open-engagements",
        params={"period": "all_time", "include_rows": "true"},
        headers=employee_auth_header(8833),
    )
    assert all_time.status_code == 200
    body = all_time.json()
    # includes null-start running B2B
    assert body["meta"]["total"] == 4
    assert body["meta"]["b2b"] == 3
    assert body["meta"]["b2c"] == 1
    codes = {row["engagement_code"] for row in body["data"]}
    assert "B2B-NULL-88204" in codes
    assert "B2B-DONE-88203" not in codes  # completed excluded
    row = next(r for r in body["data"] if r["engagement_code"] == "B2B-ONG-88201")
    assert row["type"] == "B2B"
    assert row["city"] == "Mumbai"
    assert "package" in row
    assert "start_date" in row and "end_date" in row


@pytest.mark.asyncio
async def test_command_tickets_open_solved_and_null_created(async_client, test_db_session):
    from datetime import datetime, timezone

    from modules.support.models import SupportTicket
    from modules.users.models import User

    await seed_employee(test_db_session, employee_id=8834, role="admin")
    user = User(
        user_id=88340,
        first_name="Tick",
        last_name="Et",
        phone="8834000000",
        age=28,
        status="active",
    )
    test_db_session.add(user)
    await test_db_session.flush()
    now = datetime.now(timezone.utc)
    test_db_session.add_all(
        [
            SupportTicket(
                ticket_id=88341,
                user_id=88340,
                contact_input="8834000000",
                query_text="Open issue",
                status="open",
                created_at=now,
            ),
            SupportTicket(
                ticket_id=88342,
                user_id=88340,
                contact_input="help@example.com",
                query_text="Resolved issue",
                status="resolved",
                created_at=now,
            ),
        ]
    )
    await test_db_session.commit()

    ranged = await async_client.get(
        "/admin/dashboard/command/tickets",
        params={"period": "this_week", "include_rows": "false"},
        headers=employee_auth_header(8834),
    )
    assert ranged.status_code == 200
    meta = ranged.json()["meta"]
    assert meta["open"] == 1
    assert meta["solved"] == 1
    assert meta["total"] == 2

    all_time = await async_client.get(
        "/admin/dashboard/command/tickets",
        params={"period": "all_time", "include_rows": "true"},
        headers=employee_auth_header(8834),
    )
    assert all_time.status_code == 200
    body = all_time.json()
    assert body["meta"]["open"] == 1
    assert body["meta"]["solved"] == 1
    assert body["meta"]["total"] == 2
    assert len(body["data"]) == 2
    sample = next(r for r in body["data"] if r["ticket_id"] == 88341)
    assert sample["raised_by"]["name"] == "Tick Et"
    assert sample["raised_by"]["phone"] == "8834000000"
    assert sample["contact"] == "8834000000"
    assert sample["query"] == "Open issue"
    assert sample["status"] == "open"


@pytest.mark.asyncio
async def test_command_consultation_done_null_stamp_all_time_only(
    async_client, test_db_session
):
    from datetime import date, datetime, timezone

    from modules.engagements.models import Engagement, EngagementParticipant
    from modules.experts.models import ConsultationBooking
    from modules.users.models import User

    await seed_employee(test_db_session, employee_id=8835, role="admin")
    today = date.today()
    user = User(
        user_id=88350,
        first_name="Con",
        last_name="Sult",
        phone="8835000000",
        age=35,
        status="active",
    )
    test_db_session.add(user)
    await test_db_session.flush()
    test_db_session.add(
        Engagement(
            engagement_id=88350,
            engagement_code="CONS-88350",
            engagement_name="Consult Camp",
            organization_id=None,
            city="Pune",
            start_date=today,
            end_date=today,
            status="running",
            slot_duration=20,
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        EngagementParticipant(
            engagement_participant_id=88350,
            engagement_id=88350,
            user_id=88350,
            booked_by_user_id=88350,
        )
    )
    await test_db_session.flush()
    now = datetime.now(timezone.utc)
    test_db_session.add_all(
        [
            ConsultationBooking(
                consultation_id=88351,
                engagement_participant_id=88350,
                expert_type="nutritionist",
                want=True,
                done=True,
                consultation_done_at=now,
            ),
            ConsultationBooking(
                consultation_id=88352,
                engagement_participant_id=88350,
                expert_type="physician",
                want=True,
                done=True,
                consultation_done_at=None,
            ),
        ]
    )
    await test_db_session.commit()

    ranged = await async_client.get(
        "/admin/dashboard/command/consultation-done",
        params={"period": "this_week", "include_rows": "false"},
        headers=employee_auth_header(8835),
    )
    assert ranged.status_code == 200
    # Distinct user with stamped done booking only
    assert ranged.json()["meta"]["total"] == 1
    assert ranged.json()["meta"]["b2c"] == 1

    all_time = await async_client.get(
        "/admin/dashboard/command/consultation-done",
        params={"period": "all_time", "include_rows": "false"},
        headers=employee_auth_header(8835),
    )
    assert all_time.status_code == 200
    # Same user still counts once even with a null-stamp done booking
    assert all_time.json()["meta"]["total"] == 1


@pytest.mark.asyncio
async def test_command_blood_report_null_stamp_all_time_only(async_client, test_db_session):
    from datetime import date, datetime, timezone

    from modules.engagements.blood_booking_enums import BloodBookingRelation, BloodBookingStatus
    from modules.engagements.models import Engagement, EngagementParticipant, ParticipantBloodBooking
    from modules.users.models import User

    await seed_employee(test_db_session, employee_id=8836, role="admin")
    today = date.today()
    user = User(
        user_id=88360,
        first_name="Blood",
        last_name="Report",
        phone="8836000000",
        age=40,
        status="active",
    )
    test_db_session.add(user)
    await test_db_session.flush()
    test_db_session.add(
        Engagement(
            engagement_id=88360,
            engagement_code="BLD-88360",
            engagement_name="Blood Camp",
            organization_id=None,
            city="Goa",
            start_date=today,
            end_date=today,
            status="running",
            slot_duration=20,
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        EngagementParticipant(
            engagement_participant_id=88360,
            engagement_id=88360,
            user_id=88360,
            booked_by_user_id=88360,
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        ParticipantBloodBooking(
            engagement_participant_id=88360,
            relation=BloodBookingRelation.primary.value,
            status=BloodBookingStatus.active.value,
            diagnostic_report_url="https://example.com/blood.pdf",
            report_received_at=None,
            collected_at=datetime.now(timezone.utc),
        )
    )
    await test_db_session.commit()

    ranged = await async_client.get(
        "/admin/dashboard/command/blood-report-generated",
        params={"period": "this_week", "include_rows": "false"},
        headers=employee_auth_header(8836),
    )
    assert ranged.status_code == 200
    assert ranged.json()["meta"]["total"] == 0

    all_time = await async_client.get(
        "/admin/dashboard/command/blood-report-generated",
        params={"period": "all_time", "include_rows": "true"},
        headers=employee_auth_header(8836),
    )
    assert all_time.status_code == 200
    assert all_time.json()["meta"]["total"] == 1
    assert all_time.json()["meta"]["b2c"] == 1
    assert len(all_time.json()["data"]) == 1


@pytest.mark.asyncio
async def test_command_people_registered_blood_test_with_consultation_fields(
    async_client, test_db_session
):
    """Composite consultation types must still expose package / blood / lab columns."""
    from datetime import date, datetime, time, timezone

    from sqlalchemy import text

    from modules.diagnostics.models import DiagnosticPackage
    from modules.engagements.blood_booking_enums import BloodBookingRelation, BloodBookingStatus
    from modules.engagements.models import Engagement, EngagementParticipant, ParticipantBloodBooking
    from modules.users.models import User

    await seed_employee(test_db_session, employee_id=8837, role="admin")

    await test_db_session.execute(
        text(
            "INSERT INTO engagement_types (code, display_name, is_active) "
            "VALUES (:code, :dn, true) "
            "ON CONFLICT (code) DO UPDATE SET display_name = EXCLUDED.display_name, is_active = true"
        ),
        {
            "code": "blood_test_with_consultation",
            "dn": "Blood Test with Consultation",
        },
    )
    await test_db_session.flush()
    type_id = int(
        (
            await test_db_session.execute(
                text(
                    "SELECT id FROM engagement_types WHERE code = 'blood_test_with_consultation'"
                )
            )
        ).scalar_one()
    )

    pkg = DiagnosticPackage(
        diagnostic_package_id=88370,
        package_name="Super Panel",
        package_for="public",
        status="active",
    )
    test_db_session.add(pkg)
    await test_db_session.flush()

    today = date.today()
    user = User(
        user_id=88370,
        first_name="Ada",
        last_name="Blood",
        phone="8837000000",
        age=32,
        gender="female",
        status="active",
        created_at=datetime.now(timezone.utc),
    )
    test_db_session.add(user)
    await test_db_session.flush()

    test_db_session.add(
        Engagement(
            engagement_id=88370,
            engagement_code="BTC-88370",
            engagement_name="Blood+Consult Camp",
            organization_id=None,
            city="Bengaluru",
            start_date=today,
            end_date=today,
            status="running",
            slot_duration=20,
            engagement_type=type_id,
            diagnostic_package_id=88370,
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        EngagementParticipant(
            engagement_participant_id=88370,
            engagement_id=88370,
            user_id=88370,
            booked_by_user_id=88370,
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        ParticipantBloodBooking(
            engagement_participant_id=88370,
            collection_date=today,
            collection_time=time(9, 30),
            relation=BloodBookingRelation.primary.value,
            status=BloodBookingStatus.active.value,
            collected_at=None,
            diagnostic_report_url="https://example.com/lab-88370.pdf",
        )
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/admin/dashboard/command/people-registered",
        params={"period": "all_time", "include_rows": "true", "limit": 100},
        headers=employee_auth_header(8837),
    )
    assert response.status_code == 200
    rows = response.json()["data"]
    row = next(r for r in rows if r["user_id"] == 88370)
    assert row["engagement"] == "Blood+Consult Camp"
    assert row["package"] == "Super Panel"
    assert row["collection"].startswith(today.isoformat())
    assert "09:30" in row["collection"]
    assert row["blood_collection"] == "pending"
    assert row["lab_report"] == "loaded"
