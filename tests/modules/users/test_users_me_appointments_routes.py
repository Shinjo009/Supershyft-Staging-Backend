"""Tests for GET /users/me/appointments."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest
from sqlalchemy import text

from modules.engagements.blood_booking_enums import BloodBookingRelation, BloodBookingStatus
from modules.engagements.models import Engagement, EngagementParticipant, ParticipantBloodBooking
from modules.experts.models import ConsultationBooking, Expert
from modules.users.models import User
from modules.users.appointments import derive_user_consultation_appointment_status
from tests.helpers.auth import user_auth_header


def _auth(user_id: int) -> dict[str, str]:
    return user_auth_header(user_id)


async def _ensure_engagement_type(test_db_session, code: str, display_name: str | None = None) -> int:
    name = display_name or code.replace("_", " ").title()
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_types (code, display_name, is_active) "
            "VALUES (:code, :name, true) "
            "ON CONFLICT (code) DO NOTHING"
        ),
        {"code": code, "name": name},
    )
    await test_db_session.commit()
    result = await test_db_session.execute(
        text("SELECT id FROM engagement_types WHERE code = :code LIMIT 1"),
        {"code": code},
    )
    return int(result.scalar_one())


async def _seed_user(test_db_session, user_id: int) -> None:
    test_db_session.add(
        User(
            user_id=user_id,
            age=30,
            phone=f"{user_id:010d}"[-10:],
            status="active",
            first_name="Appt",
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
    engagement_type_code: str = "consultation",
    engagement_status: str = "scheduled",
    want: bool | None = True,
    done: bool = False,
    expert_id: int = 1,
    consultation_date: date | None = date(2026, 3, 15),
) -> None:
    type_id = await _ensure_engagement_type(test_db_session, engagement_type_code)

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
            engagement_name=f"Eng {engagement_id}",
            organization_id=None,
            engagement_code=f"APT{engagement_id}",
            engagement_type=type_id,
            city="Mumbai",
            slot_duration=30,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 1),
            status=engagement_status,
            consultation_mode="online",
            blood_collection_type="camp_collection",
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
            consultation_date=consultation_date,
            consultation_slot="09:00",
        )
    )
    await test_db_session.commit()


async def _seed_blood_row(
    test_db_session,
    *,
    blood_booking_id: int | None = None,
    engagement_id: int,
    user_id: int,
    participant_id: int,
    engagement_type_code: str = "blood_test",
    engagement_status: str = "scheduled",
    collection_date: date | None = date(2026, 3, 10),
    status: BloodBookingStatus = BloodBookingStatus.active,
    collected_at: datetime | None = None,
    relation: BloodBookingRelation = BloodBookingRelation.primary,
) -> int:
    type_id = await _ensure_engagement_type(test_db_session, engagement_type_code)

    existing = await test_db_session.get(Engagement, engagement_id)
    if existing is None:
        test_db_session.add(
            Engagement(
                engagement_id=engagement_id,
                engagement_name=f"Blood {engagement_id}",
                organization_id=None,
                engagement_code=f"BLD{engagement_id}",
                engagement_type=type_id,
                city="Mumbai",
                slot_duration=30,
                start_date=date(2026, 3, 1),
                end_date=date(2026, 3, 1),
                status=engagement_status,
                blood_collection_type="home_collection",
            )
        )
        await test_db_session.flush()

    existing_part = await test_db_session.get(EngagementParticipant, participant_id)
    if existing_part is None:
        test_db_session.add(
            EngagementParticipant(
                engagement_participant_id=participant_id,
                engagement_id=engagement_id,
                user_id=user_id,
                booked_by_user_id=user_id,
            )
        )
        await test_db_session.flush()

    row_kwargs: dict = {
        "engagement_participant_id": participant_id,
        "collection_date": collection_date,
        "collection_time": time(7, 30),
        "collection_cabin": "Cabin 10",
        "relation": relation.value,
        "status": status.value,
        "booking_id": f"BK-{engagement_id}-{participant_id}",
    }
    if blood_booking_id is not None:
        row_kwargs["id"] = blood_booking_id
    if collected_at is not None:
        row_kwargs["collected_at"] = collected_at

    blood = ParticipantBloodBooking(**row_kwargs)
    test_db_session.add(blood)
    await test_db_session.commit()
    await test_db_session.refresh(blood)
    return int(blood.id)


def _assert_consultation_fields(row: dict) -> None:
    assert row["appointment_type"] == "consultation"
    assert "consultation_id" in row
    assert row["consultation_mode"] in ("online", "offline")
    assert "engagement_id" in row and row["engagement_id"] is not None
    assert "status" in row


def _assert_blood_fields(row: dict) -> None:
    assert row["appointment_type"] == "blood_test"
    assert "blood_booking_id" in row
    assert row["engagement_id"] is not None
    assert "status" in row


@pytest.mark.asyncio
async def test_list_my_appointments_requires_auth(async_client):
    response = await async_client.get("/users/me/appointments")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_my_appointments_empty(async_client, test_db_session):
    await _seed_user(test_db_session, 89001)
    response = await async_client.get("/users/me/appointments", headers=_auth(89001))
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0


@pytest.mark.asyncio
async def test_list_my_appointments_consultation_scheduled(async_client, test_db_session):
    user_id = 89002
    await _seed_user(test_db_session, user_id)
    await _seed_consultation_row(
        test_db_session,
        consultation_id=890021,
        engagement_id=89002,
        user_id=user_id,
        participant_id=890022,
    )

    response = await async_client.get(
        "/users/me/appointments?status=scheduled",
        headers=_auth(user_id),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1
    row = data[0]
    _assert_consultation_fields(row)
    assert row["status"] == "scheduled"
    assert row["engagement_type"] == "consultation"


@pytest.mark.asyncio
async def test_list_my_appointments_bio_ai_with_consultation_scheduled(async_client, test_db_session):
    user_id = 89003
    await _seed_user(test_db_session, user_id)
    await _seed_consultation_row(
        test_db_session,
        consultation_id=890031,
        engagement_id=89003,
        user_id=user_id,
        participant_id=890032,
        engagement_type_code="bio_ai_with_consultation",
        want=True,
        done=False,
    )

    response = await async_client.get(
        "/users/me/appointments?status=scheduled",
        headers=_auth(user_id),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["engagement_type"] == "bio_ai_with_consultation"
    assert data[0]["status"] == "scheduled"


def test_derive_consultation_appointment_status_want_null_is_scheduled():
    assert (
        derive_user_consultation_appointment_status(
            done=False,
            want=None,
            engagement_status="scheduled",
        )
        == "scheduled"
    )


@pytest.mark.asyncio
async def test_list_my_appointments_consultation_completed(async_client, test_db_session):
    user_id = 89005
    await _seed_user(test_db_session, user_id)
    await _seed_consultation_row(
        test_db_session,
        consultation_id=890051,
        engagement_id=89005,
        user_id=user_id,
        participant_id=890052,
        want=True,
        done=True,
    )

    response = await async_client.get(
        "/users/me/appointments?status=completed",
        headers=_auth(user_id),
    )
    assert response.status_code == 200
    assert response.json()["data"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_list_my_appointments_consultation_cancelled_want_false(async_client, test_db_session):
    user_id = 89006
    await _seed_user(test_db_session, user_id)
    await _seed_consultation_row(
        test_db_session,
        consultation_id=890061,
        engagement_id=89006,
        user_id=user_id,
        participant_id=890062,
        want=False,
    )

    response = await async_client.get(
        "/users/me/appointments?status=cancelled",
        headers=_auth(user_id),
    )
    assert response.status_code == 200
    assert response.json()["data"][0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_list_my_appointments_blood_scheduled(async_client, test_db_session):
    user_id = 89007
    await _seed_user(test_db_session, user_id)
    await _seed_blood_row(
        test_db_session,
        engagement_id=89007,
        user_id=user_id,
        participant_id=890072,
    )

    response = await async_client.get(
        "/users/me/appointments?status=scheduled",
        headers=_auth(user_id),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1
    row = data[0]
    _assert_blood_fields(row)
    assert row["status"] == "scheduled"
    assert row["blood_collection_type"] == "home_collection"
    assert row["cabin"] == "Cabin 10"


@pytest.mark.asyncio
async def test_list_my_appointments_blood_completed(async_client, test_db_session):
    user_id = 89008
    await _seed_user(test_db_session, user_id)
    await _seed_blood_row(
        test_db_session,
        engagement_id=89008,
        user_id=user_id,
        participant_id=890082,
        collected_at=datetime(2026, 3, 10, 8, 0, tzinfo=timezone.utc),
    )

    response = await async_client.get(
        "/users/me/appointments?status=completed",
        headers=_auth(user_id),
    )
    assert response.status_code == 200
    assert response.json()["data"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_list_my_appointments_blood_cancelled(async_client, test_db_session):
    user_id = 89009
    await _seed_user(test_db_session, user_id)
    await _seed_blood_row(
        test_db_session,
        engagement_id=89009,
        user_id=user_id,
        participant_id=890092,
        status=BloodBookingStatus.cancelled,
    )

    response = await async_client.get(
        "/users/me/appointments?status=cancelled",
        headers=_auth(user_id),
    )
    assert response.status_code == 200
    assert response.json()["data"][0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_list_my_appointments_excludes_superseded_blood(async_client, test_db_session):
    user_id = 89010
    await _seed_user(test_db_session, user_id)
    await _seed_blood_row(
        test_db_session,
        engagement_id=89010,
        user_id=user_id,
        participant_id=890102,
        status=BloodBookingStatus.superseded,
    )

    response = await async_client.get("/users/me/appointments", headers=_auth(user_id))
    assert response.status_code == 200
    assert response.json()["data"] == []


@pytest.mark.asyncio
async def test_list_my_appointments_excludes_draft_engagement(async_client, test_db_session):
    user_id = 89011
    await _seed_user(test_db_session, user_id)
    await _seed_blood_row(
        test_db_session,
        engagement_id=89011,
        user_id=user_id,
        participant_id=890112,
        engagement_status="draft",
    )

    response = await async_client.get("/users/me/appointments", headers=_auth(user_id))
    assert response.status_code == 200
    assert response.json()["data"] == []


@pytest.mark.asyncio
async def test_list_my_appointments_mixed_sorted_by_date(async_client, test_db_session):
    user_id = 89012
    await _seed_user(test_db_session, user_id)
    await _seed_consultation_row(
        test_db_session,
        consultation_id=890121,
        engagement_id=89012,
        user_id=user_id,
        participant_id=890122,
        consultation_date=date(2026, 4, 1),
    )
    await _seed_blood_row(
        test_db_session,
        engagement_id=89013,
        user_id=user_id,
        participant_id=890132,
        collection_date=date(2026, 5, 1),
    )

    response = await async_client.get("/users/me/appointments", headers=_auth(user_id))
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 2
    assert data[0]["appointment_type"] == "blood_test"
    assert data[0]["date"] == "2026-05-01"
    assert data[1]["appointment_type"] == "consultation"
    assert data[1]["date"] == "2026-04-01"


@pytest.mark.asyncio
async def test_list_my_appointments_status_filter_isolates_rows(async_client, test_db_session):
    user_id = 89014
    await _seed_user(test_db_session, user_id)
    await _seed_consultation_row(
        test_db_session,
        consultation_id=890141,
        engagement_id=89014,
        user_id=user_id,
        participant_id=890142,
        want=True,
        done=False,
    )
    await _seed_consultation_row(
        test_db_session,
        consultation_id=890143,
        engagement_id=89015,
        user_id=user_id,
        participant_id=890152,
        want=True,
        done=True,
    )

    scheduled = await async_client.get(
        "/users/me/appointments?status=scheduled",
        headers=_auth(user_id),
    )
    assert len(scheduled.json()["data"]) == 1
    assert scheduled.json()["data"][0]["consultation_id"] == 890141

    completed = await async_client.get(
        "/users/me/appointments?status=completed",
        headers=_auth(user_id),
    )
    assert len(completed.json()["data"]) == 1
    assert completed.json()["data"][0]["consultation_id"] == 890143
