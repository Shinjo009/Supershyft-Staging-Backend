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
