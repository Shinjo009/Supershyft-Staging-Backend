"""Integration tests for user saved addresses."""

from __future__ import annotations

import pytest

from modules.users.models import User


def _auth_header(user_id: int) -> dict[str, str]:
    from tests.helpers.auth import user_auth_header
    return user_auth_header(user_id)


def _address_payload(*, line: str, city: str = "Pune", pincode: str = "411001", **extra) -> dict:
    payload = {
        "address_line1": line,
        "address_line2": "Koregaon Park",
        "landmark": "Near park",
        "city": city,
        "state": "Maharashtra",
        "pincode": pincode,
    }
    payload.update(extra)
    return payload


@pytest.mark.asyncio
async def test_list_addresses_empty(async_client, test_db_session):
    user = User(user_id=4101, age=30, phone="4101410141", status="active", first_name="A")
    test_db_session.add(user)
    await test_db_session.commit()

    response = await async_client.get("/users/me/addresses", headers=_auth_header(4101))
    assert response.status_code == 200
    assert response.json()["data"] == []


@pytest.mark.asyncio
async def test_put_me_creates_default_address_row(async_client, test_db_session):
    user = User(user_id=4102, age=30, phone="4102410241", status="active", first_name="A")
    test_db_session.add(user)
    await test_db_session.commit()

    response = await async_client.put(
        "/users/me",
        headers=_auth_header(4102),
        json={"age": 30, "address": "House 12, Lane 3, Near cafe", "city": "Pune", "pin_code": "411001"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["city"] == "Pune"

    listed = await async_client.get("/users/me/addresses", headers=_auth_header(4102))
    assert listed.status_code == 200
    rows = listed.json()["data"]
    assert len(rows) == 1
    assert rows[0]["is_default"] is True
    assert rows[0]["address_line1"] == "House 12"
    assert rows[0]["address_line2"] == "Lane 3"
    assert rows[0]["landmark"] == "Near cafe"
    assert rows[0]["pincode"] == "411001"


@pytest.mark.asyncio
async def test_create_addresses_caps_at_three(async_client, test_db_session):
    user = User(user_id=4103, age=30, phone="4103410341", status="active", first_name="A")
    test_db_session.add(user)
    await test_db_session.commit()

    headers = _auth_header(4103)
    for index in range(3):
        response = await async_client.post(
            "/users/me/addresses",
            headers=headers,
            json=_address_payload(line=f"House {index + 1}"),
        )
        assert response.status_code == 200, response.json()

    fourth = await async_client.post(
        "/users/me/addresses",
        headers=headers,
        json=_address_payload(line="House 4"),
    )
    assert fourth.status_code == 422
    assert fourth.json()["error_code"] == "ADDRESS_LIMIT_REACHED"

    listed = await async_client.get("/users/me/addresses", headers=headers)
    assert len(listed.json()["data"]) == 3


@pytest.mark.asyncio
async def test_cannot_mutate_another_users_address(async_client, test_db_session):
    owner = User(user_id=4104, age=30, phone="4104410441", status="active", first_name="Owner")
    other = User(user_id=4105, age=30, phone="4105410541", status="active", first_name="Other")
    test_db_session.add_all([owner, other])
    await test_db_session.commit()

    created = await async_client.post(
        "/users/me/addresses",
        headers=_auth_header(4104),
        json=_address_payload(line="Owner House"),
    )
    assert created.status_code == 200
    address_id = created.json()["data"]["user_address_id"]

    update = await async_client.put(
        f"/users/me/addresses/{address_id}",
        headers=_auth_header(4105),
        json={"city": "Mumbai"},
    )
    assert update.status_code == 404

    delete = await async_client.delete(
        f"/users/me/addresses/{address_id}",
        headers=_auth_header(4105),
    )
    assert delete.status_code == 404


@pytest.mark.asyncio
async def test_delete_default_promotes_oldest_remaining(async_client, test_db_session):
    user = User(user_id=4106, age=30, phone="4106410641", status="active", first_name="A")
    test_db_session.add(user)
    await test_db_session.commit()

    headers = _auth_header(4106)
    first = await async_client.post("/users/me/addresses", headers=headers, json=_address_payload(line="First"))
    second = await async_client.post("/users/me/addresses", headers=headers, json=_address_payload(line="Second"))
    assert first.status_code == 200
    assert second.status_code == 200
    first_id = first.json()["data"]["user_address_id"]
    second_id = second.json()["data"]["user_address_id"]
    assert first.json()["data"]["is_default"] is True
    assert second.json()["data"]["is_default"] is False

    deleted = await async_client.delete(f"/users/me/addresses/{first_id}", headers=headers)
    assert deleted.status_code == 200

    listed = await async_client.get("/users/me/addresses", headers=headers)
    rows = listed.json()["data"]
    assert len(rows) == 1
    assert rows[0]["user_address_id"] == second_id
    assert rows[0]["is_default"] is True

    me = await async_client.get("/users/me", headers=headers)
    assert me.json()["data"]["address"] == "Second, Koregaon Park, Near park"


@pytest.mark.asyncio
async def test_delete_last_address_clears_user_location(async_client, test_db_session):
    user = User(
        user_id=4107,
        age=30,
        phone="4107410741",
        status="active",
        first_name="A",
        address="Old Street",
        city="Delhi",
        pin_code="110001",
    )
    test_db_session.add(user)
    await test_db_session.commit()

    headers = _auth_header(4107)
    created = await async_client.post("/users/me/addresses", headers=headers, json=_address_payload(line="Only"))
    assert created.status_code == 200
    address_id = created.json()["data"]["user_address_id"]

    deleted = await async_client.delete(f"/users/me/addresses/{address_id}", headers=headers)
    assert deleted.status_code == 200

    me = await async_client.get("/users/me", headers=headers)
    data = me.json()["data"]
    assert data["address"] is None
    assert data["city"] is None
    assert data["pin_code"] is None
