"""Tests for GET /superclub/playlists."""

from __future__ import annotations

import pytest

from modules.employee.models import Employee
from modules.users.models import User, UserPreference
from tests.helpers.auth import employee_auth_header


def _auth_header(employee_id: int) -> dict[str, str]:
    return employee_auth_header(employee_id)


async def _seed_admin(test_db_session, employee_id: int = 88001) -> None:
    test_db_session.add(
        Employee(
            employee_id=employee_id,
            name="Superclub Admin",
            phone="8800100001",
            email="superclub-admin@test.example",
            role="admin",
            status="active",
        )
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_list_superclub_playlists_requires_employee(async_client):
    response = await async_client.get("/superclub/playlists")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_superclub_playlists_excludes_empty(async_client, test_db_session):
    await _seed_admin(test_db_session)
    test_db_session.add(
        User(user_id=88010, phone="8801000010", first_name="Empty", last_name="Prefs", status="active")
    )
    await test_db_session.flush()
    test_db_session.add(UserPreference(user_id=88010, sports_playlists={}))
    test_db_session.add(
        User(user_id=88011, phone="8801000011", first_name="Ada", last_name="Club", status="active", city="Bengaluru")
    )
    await test_db_session.flush()
    test_db_session.add(
        UserPreference(
            user_id=88011,
            sports_playlists={
                "sportIds": ["padel", "pickleball"],
                "otherSelected": False,
                "otherNote": "",
            },
        )
    )
    await test_db_session.commit()

    response = await async_client.get("/superclub/playlists", headers=_auth_header(88001))
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 1
    assert body["meta"]["playlists_submitted"] == 1
    assert len(body["data"]) == 1
    assert body["data"][0]["user_id"] == 88011
    assert body["data"][0]["sports_playlists"]["sportIds"] == ["padel", "pickleball"]


@pytest.mark.asyncio
async def test_list_superclub_playlists_filter_by_sport(async_client, test_db_session):
    await _seed_admin(test_db_session)
    for uid, sports in (
        (88020, ["padel"]),
        (88021, ["pickleball"]),
        (88022, []),
    ):
        test_db_session.add(User(user_id=uid, phone=f"88020000{uid % 10}", status="active"))
        await test_db_session.flush()
        payload = {
            "sportIds": sports,
            "otherSelected": uid == 88022,
            "otherNote": "Kite" if uid == 88022 else "",
        }
        test_db_session.add(UserPreference(user_id=uid, sports_playlists=payload))
    await test_db_session.commit()

    response = await async_client.get(
        "/superclub/playlists?sport_id=padel",
        headers=_auth_header(88001),
    )
    assert response.status_code == 200
    ids = {row["user_id"] for row in response.json()["data"]}
    assert ids == {88020}

    response_other = await async_client.get(
        "/superclub/playlists?sport_id=other",
        headers=_auth_header(88001),
    )
    assert response_other.status_code == 200
    assert response_other.json()["meta"]["total"] == 1
    assert response_other.json()["data"][0]["user_id"] == 88022


@pytest.mark.asyncio
async def test_list_superclub_playlists_search(async_client, test_db_session):
    await _seed_admin(test_db_session)
    test_db_session.add(
        User(user_id=88030, phone="9900000030", first_name="Search", last_name="Me", status="active")
    )
    await test_db_session.flush()
    test_db_session.add(
        UserPreference(
            user_id=88030,
            sports_playlists={"sportIds": ["yoga"], "otherSelected": False, "otherNote": ""},
        )
    )
    test_db_session.add(
        User(user_id=88031, phone="9900000031", first_name="Other", last_name="Person", status="active")
    )
    await test_db_session.flush()
    test_db_session.add(
        UserPreference(
            user_id=88031,
            sports_playlists={"sportIds": ["cricket"], "otherSelected": False, "otherNote": ""},
        )
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/superclub/playlists?search=Search",
        headers=_auth_header(88001),
    )
    assert response.status_code == 200
    assert response.json()["meta"]["total"] == 1
    assert response.json()["data"][0]["first_name"] == "Search"
    assert response.json()["meta"]["sport_counts"].get("yoga") == 1
    assert "cricket" not in response.json()["meta"]["sport_counts"]
