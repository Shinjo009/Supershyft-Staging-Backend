"""Tests for GET /users/me/consultations."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text

from modules.engagements.models import Engagement, EngagementParticipant
from modules.experts.models import ConsultationBooking, Expert
from modules.users.models import User
from tests.helpers.auth import user_auth_header


def _auth(user_id: int) -> dict[str, str]:
    return user_auth_header(user_id)


async def _ensure_consultation_engagement_type(test_db_session) -> int:
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_types (code, display_name, is_active) "
            "VALUES ('consultation', 'Consultation', true) "
            "ON CONFLICT (code) DO NOTHING"
        )
    )
    await test_db_session.commit()
    result = await test_db_session.execute(
        text("SELECT id FROM engagement_types WHERE code = 'consultation' LIMIT 1")
    )
    return int(result.scalar_one())


async def _seed_user(test_db_session, user_id: int) -> None:
    test_db_session.add(
        User(
            user_id=user_id,
            age=30,
            phone=f"{user_id:010d}"[-10:],
            status="active",
            first_name="Consult",
        )
    )
    await test_db_session.commit()


async def _seed_consultation_row(
    test_db_session,
    *,
    consultation_id: int,
    engagement_id: int,
    user_id: int,
    participant_id: int,
    engagement_status: str = "scheduled",
    want: bool = True,
    done: bool = False,
    expert_id: int = 1,
) -> None:
    type_id = await _ensure_consultation_engagement_type(test_db_session)

    existing_expert = await test_db_session.get(Expert, expert_id)
    if existing_expert is None:
        test_db_session.add(
            Expert(
                expert_id=expert_id,
                expert_type="doctor",
                specialization="GP",
                status="active",
                appointment_fee_paise=10000,
            )
        )
        await test_db_session.flush()

    test_db_session.add(
        Engagement(
            engagement_id=engagement_id,
            engagement_name=f"Consult {engagement_id}",
            organization_id=None,
            engagement_code=f"CNS{engagement_id}",
            engagement_type=type_id,
            city="Mumbai",
            slot_duration=30,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 1),
            status=engagement_status,
            consultation_mode="online",
        )
    )
    await test_db_session.flush()

    test_db_session.add(
        EngagementParticipant(
            engagement_participant_id=participant_id,
            engagement_id=engagement_id,
            user_id=user_id,
            booked_by_user_id=user_id,
        )
    )
    await test_db_session.flush()

    test_db_session.add(
        ConsultationBooking(
            consultation_id=consultation_id,
            engagement_participant_id=participant_id,
            expert_type="doctor",
            expert_id=expert_id,
            want=want,
            done=done,
            consultation_date=date(2026, 3, 15),
            consultation_slot="09:00",
        )
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_list_my_consultations_requires_auth(async_client):
    response = await async_client.get("/users/me/consultations")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_my_consultations_empty(async_client, test_db_session):
    await _seed_user(test_db_session, 88001)
    response = await async_client.get("/users/me/consultations", headers=_auth(88001))
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0


@pytest.mark.asyncio
async def test_list_my_consultations_scheduled_filter(async_client, test_db_session):
    user_id = 88002
    await _seed_user(test_db_session, user_id)
    await _seed_consultation_row(
        test_db_session,
        consultation_id=880021,
        engagement_id=88002,
        user_id=user_id,
        participant_id=880022,
        engagement_status="scheduled",
        want=True,
        done=False,
    )

    for path in ("/users/me/consultations", "/users/me/consultations?status=scheduled"):
        response = await async_client.get(path, headers=_auth(user_id))
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        row = data[0]
        assert row["status"] == "scheduled"
        assert row["engagement_id"] == 88002
        assert row["engagement_type"] == "consultation"
        assert row["consultation_mode"] == "online"
        assert row["expert_type"] == "doctor"
        assert row["expert_id"] == 1
        assert row["want"] is True
        assert row["done"] is False


@pytest.mark.asyncio
async def test_list_my_consultations_completed_filter(async_client, test_db_session):
    user_id = 88003
    await _seed_user(test_db_session, user_id)
    await _seed_consultation_row(
        test_db_session,
        consultation_id=880031,
        engagement_id=88003,
        user_id=user_id,
        participant_id=880032,
        want=True,
        done=True,
    )

    response = await async_client.get(
        "/users/me/consultations?status=completed",
        headers=_auth(user_id),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["status"] == "completed"
    _assert_required_fields(data[0])


@pytest.mark.asyncio
async def test_list_my_consultations_cancelled_by_want_false(async_client, test_db_session):
    user_id = 88004
    await _seed_user(test_db_session, user_id)
    await _seed_consultation_row(
        test_db_session,
        consultation_id=880041,
        engagement_id=88004,
        user_id=user_id,
        participant_id=880042,
        want=False,
        done=False,
    )

    response = await async_client.get(
        "/users/me/consultations?status=cancelled",
        headers=_auth(user_id),
    )
    assert response.status_code == 200
    assert len(response.json()["data"]) == 1
    assert response.json()["data"][0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_list_my_consultations_cancelled_by_engagement(async_client, test_db_session):
    user_id = 88005
    await _seed_user(test_db_session, user_id)
    await _seed_consultation_row(
        test_db_session,
        consultation_id=880051,
        engagement_id=88005,
        user_id=user_id,
        participant_id=880052,
        engagement_status="cancelled",
        want=True,
        done=False,
    )

    response = await async_client.get(
        "/users/me/consultations?status=cancelled",
        headers=_auth(user_id),
    )
    assert response.status_code == 200
    assert response.json()["data"][0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_list_my_consultations_status_filter_excludes_other_rows(async_client, test_db_session):
    user_id = 88006
    await _seed_user(test_db_session, user_id)
    await _seed_consultation_row(
        test_db_session,
        consultation_id=880061,
        engagement_id=88006,
        user_id=user_id,
        participant_id=880062,
        want=True,
        done=False,
    )
    await _seed_consultation_row(
        test_db_session,
        consultation_id=880063,
        engagement_id=88007,
        user_id=user_id,
        participant_id=880072,
        want=True,
        done=True,
    )

    response = await async_client.get(
        "/users/me/consultations?status=completed",
        headers=_auth(user_id),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["consultation_id"] == 880063
    assert data[0]["status"] == "completed"

    scheduled_resp = await async_client.get(
        "/users/me/consultations?status=scheduled",
        headers=_auth(user_id),
    )
    assert len(scheduled_resp.json()["data"]) == 1
    assert scheduled_resp.json()["data"][0]["consultation_id"] == 880061


@pytest.mark.asyncio
async def test_list_my_consultations_unfiltered_includes_required_fields(async_client, test_db_session):
    user_id = 88008
    await _seed_user(test_db_session, user_id)
    await _seed_consultation_row(
        test_db_session,
        consultation_id=880081,
        engagement_id=88008,
        user_id=user_id,
        participant_id=880082,
    )

    response = await async_client.get("/users/me/consultations", headers=_auth(user_id))
    assert response.status_code == 200
    for row in response.json()["data"]:
        _assert_required_fields(row)


def _assert_required_fields(row: dict) -> None:
    assert "engagement_id" in row and row["engagement_id"] is not None
    assert row["engagement_type"] == "consultation"
    assert row["consultation_mode"] in ("online", "offline")
