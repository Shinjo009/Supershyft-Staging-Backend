"""Command dashboard detail list search (name/phone + notification engagement/name)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from modules.dashboard.command_service import (
    _filter_audience_by_search,
    _filter_user_ids_by_search,
)
from modules.engagements.models import Engagement
from modules.notifications.models import Notification, NotificationService
from modules.users.models import User
from tests.helpers.auth import employee_auth_header, seed_employee


async def _seed_users(test_db_session):
    users = [
        User(
            user_id=89001,
            age=30,
            phone="9000000001",
            status="active",
            first_name="Ada",
            last_name="Lovelace",
            created_at=datetime(2024, 1, 10, tzinfo=timezone.utc),
        ),
        User(
            user_id=89002,
            age=31,
            phone="9000000002",
            status="active",
            first_name="Grace",
            last_name="Hopper",
            created_at=datetime(2024, 1, 11, tzinfo=timezone.utc),
        ),
        User(
            user_id=89003,
            age=32,
            phone="9111222333",
            status="active",
            first_name="Alan",
            last_name="Turing",
            created_at=datetime(2024, 1, 12, tzinfo=timezone.utc),
        ),
    ]
    test_db_session.add_all(users)
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_filter_user_ids_by_name_and_phone(test_db_session):
    await _seed_users(test_db_session)
    ids = [89001, 89002, 89003]

    by_name = await _filter_user_ids_by_search(test_db_session, ids, "Ada")
    assert by_name == [89001]

    by_phone = await _filter_user_ids_by_search(test_db_session, ids, "9111222333")
    assert by_phone == [89003]

    by_empty = await _filter_user_ids_by_search(test_db_session, ids, None)
    assert by_empty == ids

    by_miss = await _filter_user_ids_by_search(test_db_session, ids, "Nobody")
    assert by_miss == []


@pytest.mark.asyncio
async def test_filter_audience_by_search(test_db_session):
    await _seed_users(test_db_session)
    audience = {89001: "B2C", 89002: "B2B", 89003: "B2C"}
    filtered = await _filter_audience_by_search(test_db_session, audience, "Hopper")
    assert filtered == {89002: "B2B"}


@pytest.mark.asyncio
async def test_people_registered_search_by_name(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=89010, role="admin")
    await _seed_users(test_db_session)

    headers = employee_auth_header(89010)
    all_res = await async_client.get(
        "/admin/dashboard/command/people-registered",
        params={"period": "all_time", "include_rows": "true", "limit": 100},
        headers=headers,
    )
    assert all_res.status_code == 200
    all_ids = {r["user_id"] for r in all_res.json()["data"]}
    assert {89001, 89002, 89003}.issubset(all_ids)

    name_res = await async_client.get(
        "/admin/dashboard/command/people-registered",
        params={
            "period": "all_time",
            "include_rows": "true",
            "limit": 100,
            "search": "Lovelace",
        },
        headers=headers,
    )
    assert name_res.status_code == 200
    body = name_res.json()
    assert body["meta"]["total"] == 1
    assert [r["user_id"] for r in body["data"]] == [89001]
    assert body["data"][0]["person"]["name"].startswith("Ada")


@pytest.mark.asyncio
async def test_people_registered_search_by_phone(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=89011, role="admin")
    await _seed_users(test_db_session)

    res = await async_client.get(
        "/admin/dashboard/command/people-registered",
        params={
            "period": "all_time",
            "include_rows": "true",
            "limit": 100,
            "search": "9000000002",
        },
        headers=employee_auth_header(89011),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["user_id"] == 89002


@pytest.mark.asyncio
async def test_open_engagements_unchanged_without_search(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=89012, role="admin")
    res = await async_client.get(
        "/admin/dashboard/command/open-engagements",
        params={"period": "all_time", "include_rows": "false"},
        headers=employee_auth_header(89012),
    )
    assert res.status_code == 200
    assert "total" in res.json()["meta"]


@pytest.mark.asyncio
async def test_failed_notifications_search_by_engagement(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=89013, role="admin")
    await _seed_users(test_db_session)

    test_db_session.add(
        NotificationService(
            notification_service_id=89013,
            service_key="cmd_search_svc",
            display_name="Cmd Search",
            channel="whatsapp",
            is_active=True,
        )
    )
    test_db_session.add(
        Engagement(
            engagement_id=89013,
            engagement_code="SRCH-89013",
            engagement_name="Searchable Camp Alpha",
            status="running",
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        Notification(
            notification_id=89013,
            service_key="cmd_search_svc",
            status="failed",
            channel="whatsapp",
            engagement_id=89013,
            user={"user_ids": [89001]},
            message="boom",
            dispatched_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
    )
    test_db_session.add(
        Notification(
            notification_id=89014,
            service_key="cmd_search_svc",
            status="failed",
            channel="whatsapp",
            engagement_id=None,
            user={"user_ids": [89002]},
            message="other",
            dispatched_at=datetime(2024, 6, 2, tzinfo=timezone.utc),
        )
    )
    await test_db_session.commit()

    headers = employee_auth_header(89013)
    by_eng = await async_client.get(
        "/admin/dashboard/command/notification-health/failed",
        params={"period": "all_time", "search": "Searchable Camp"},
        headers=headers,
    )
    assert by_eng.status_code == 200
    eng_ids = [r.get("notification_id") for r in by_eng.json()["data"]]
    assert 89013 in eng_ids
    assert 89014 not in eng_ids

    by_name = await async_client.get(
        "/admin/dashboard/command/notification-health/failed",
        params={"period": "all_time", "search": "Ada"},
        headers=headers,
    )
    assert by_name.status_code == 200
    name_ids = [r.get("notification_id") for r in by_name.json()["data"]]
    assert 89013 in name_ids
    assert 89014 not in name_ids
