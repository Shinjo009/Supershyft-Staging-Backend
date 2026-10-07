"""Tests for camp EOD GET /engagements/{id}/booking-summary."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from modules.engagements.blood_booking_enums import BloodBookingRelation, BloodBookingStatus
from modules.engagements.models import Engagement, EngagementParticipant, ParticipantBloodBooking
from modules.users.models import User
from tests.helpers.auth import employee_auth_header, seed_employee


TODAY = date(2026, 10, 6)


def _auth_header(employee_id: int) -> dict[str, str]:
    return employee_auth_header(employee_id)


def _ist_collected_at(day: date) -> datetime:
    """UTC instant that falls on `day` in Asia/Kolkata (UTC+5:30)."""
    return datetime(day.year, day.month, day.day, 6, 0, tzinfo=timezone.utc)


async def _engagement_type_id(test_db_session, code: str) -> int:
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_types (code, display_name, is_active) "
            "VALUES (:code, :dn, true) "
            "ON CONFLICT (code) DO UPDATE SET is_active = true"
        ),
        {"code": code, "dn": code},
    )
    await test_db_session.commit()
    row = (
        await test_db_session.execute(
            text("SELECT id FROM engagement_types WHERE code = :code"),
            {"code": code},
        )
    ).one()
    return int(row[0])


async def _seed_engagement(test_db_session, *, engagement_id: int, type_code: str):
    type_id = await _engagement_type_id(test_db_session, type_code)
    test_db_session.add(
        Engagement(
            engagement_id=engagement_id,
            engagement_code=f"ENG{engagement_id}",
            engagement_type=type_id,
            assessment_package_id=1,
            diagnostic_package_id=1,
            slot_duration=20,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 10, 31),
            status="running",
        )
    )
    await test_db_session.commit()


async def _seed_user(test_db_session, user_id: int):
    test_db_session.add(
        User(
            user_id=user_id,
            age=30,
            phone=f"{user_id:010d}",
            status="active",
        )
    )
    await test_db_session.flush()


async def _add_participant_booking(
    test_db_session,
    *,
    engagement_id: int,
    user_id: int,
    engagement_participant_id: int,
    collection_date: date | None,
    status: BloodBookingStatus,
    relation: BloodBookingRelation = BloodBookingRelation.primary,
    booking_id: str | None = None,
    collected_at: datetime | None = None,
):
    await _seed_user(test_db_session, user_id)
    test_db_session.add(
        EngagementParticipant(
            engagement_participant_id=engagement_participant_id,
            engagement_id=engagement_id,
            user_id=user_id,
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        ParticipantBloodBooking(
            engagement_participant_id=engagement_participant_id,
            collection_date=collection_date,
            relation=relation.value,
            status=status.value,
            booking_id=booking_id,
            collected_at=collected_at,
        )
    )


@pytest.fixture
def freeze_ist_today(monkeypatch):
    monkeypatch.setattr("modules.engagements.service._ist_today", lambda: TODAY)


@pytest.mark.asyncio
async def test_booking_summary_zeros_when_no_bookings(
    async_client, test_db_session, freeze_ist_today
):
    await seed_employee(test_db_session, employee_id=7910)
    await _seed_engagement(test_db_session, engagement_id=79101, type_code="booking_summary_empty")
    await _seed_user(test_db_session, 79111)
    test_db_session.add(
        EngagementParticipant(
            engagement_participant_id=79111,
            engagement_id=79101,
            user_id=79111,
        )
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/engagements/79101/booking-summary",
        headers=_auth_header(7910),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["today_expected_booking_count"] == 0
    assert data["today_pending_booking_count"] == 0
    assert data["today_booking_count"] == 0
    assert data["total_booking_count"] == 0
    assert data["pending_booking_count"] == 0
    assert data["as_of_date"] == "2026-10-06"


@pytest.mark.asyncio
async def test_booking_summary_not_found(async_client, test_db_session, freeze_ist_today):
    await seed_employee(test_db_session, employee_id=7911)
    response = await async_client.get(
        "/engagements/999999/booking-summary",
        headers=_auth_header(7911),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_booking_summary_today_total_pending_mapping(
    async_client, test_db_session, freeze_ist_today
):
    await seed_employee(test_db_session, employee_id=7912)
    await _seed_engagement(test_db_session, engagement_id=79102, type_code="booking_summary_dates")

    await _add_participant_booking(
        test_db_session,
        engagement_id=79102,
        user_id=79201,
        engagement_participant_id=79201,
        collection_date=date(2026, 10, 4),
        status=BloodBookingStatus.active,
        booking_id="yesterday-1",
        collected_at=_ist_collected_at(date(2026, 10, 5)),
    )
    await _add_participant_booking(
        test_db_session,
        engagement_id=79102,
        user_id=79202,
        engagement_participant_id=79202,
        collection_date=TODAY,
        status=BloodBookingStatus.active,
        booking_id="today-1",
        collected_at=_ist_collected_at(TODAY),
    )
    await _add_participant_booking(
        test_db_session,
        engagement_id=79102,
        user_id=79203,
        engagement_participant_id=79203,
        collection_date=date(2026, 10, 7),
        status=BloodBookingStatus.active,
        booking_id="future-1",
        collected_at=_ist_collected_at(date(2026, 10, 7)),
    )
    await _add_participant_booking(
        test_db_session,
        engagement_id=79102,
        user_id=79204,
        engagement_participant_id=79204,
        collection_date=date(2026, 10, 8),
        status=BloodBookingStatus.active,
        booking_id="pending-no-collected",
    )
    await _add_participant_booking(
        test_db_session,
        engagement_id=79102,
        user_id=79205,
        engagement_participant_id=79205,
        collection_date=TODAY,
        status=BloodBookingStatus.active,
        booking_id=None,
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/engagements/79102/booking-summary",
        headers=_auth_header(7912),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["today_expected_booking_count"] == 2
    assert data["today_pending_booking_count"] == 1
    assert data["today_booking_count"] == 1
    assert data["total_booking_count"] == 2
    assert data["pending_booking_count"] == 4


@pytest.mark.asyncio
async def test_booking_summary_excludes_superseded_and_resample(
    async_client, test_db_session, freeze_ist_today
):
    await seed_employee(test_db_session, employee_id=7913)
    await _seed_engagement(test_db_session, engagement_id=79103, type_code="booking_summary_dedupe")
    await _seed_user(test_db_session, 79301)
    test_db_session.add(
        EngagementParticipant(
            engagement_participant_id=79301,
            engagement_id=79103,
            user_id=79301,
        )
    )
    await test_db_session.flush()
    test_db_session.add_all(
        [
            ParticipantBloodBooking(
                engagement_participant_id=79301,
                collection_date=date(2026, 10, 4),
                relation=BloodBookingRelation.primary.value,
                status=BloodBookingStatus.superseded.value,
                booking_id="old-slot",
                collected_at=_ist_collected_at(date(2026, 10, 4)),
            ),
            ParticipantBloodBooking(
                engagement_participant_id=79301,
                collection_date=TODAY,
                relation=BloodBookingRelation.reschedule.value,
                status=BloodBookingStatus.active.value,
                booking_id="new-slot",
                collected_at=_ist_collected_at(TODAY),
            ),
            ParticipantBloodBooking(
                engagement_participant_id=79301,
                collection_date=TODAY,
                relation=BloodBookingRelation.resample.value,
                status=BloodBookingStatus.active.value,
                booking_id="resample-slot",
                collected_at=_ist_collected_at(TODAY),
            ),
        ]
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/engagements/79103/booking-summary",
        headers=_auth_header(7913),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["today_expected_booking_count"] == 1
    assert data["today_pending_booking_count"] == 0
    assert data["total_booking_count"] == 1
    assert data["today_booking_count"] == 1
    assert data["pending_booking_count"] == 1


@pytest.mark.asyncio
async def test_booking_summary_cancel_then_rebook_counts_active_only(
    async_client, test_db_session, freeze_ist_today
):
    await seed_employee(test_db_session, employee_id=7914)
    await _seed_engagement(test_db_session, engagement_id=79104, type_code="booking_summary_rebook")
    await _seed_user(test_db_session, 79401)
    test_db_session.add(
        EngagementParticipant(
            engagement_participant_id=79401,
            engagement_id=79104,
            user_id=79401,
        )
    )
    await test_db_session.flush()
    test_db_session.add_all(
        [
            ParticipantBloodBooking(
                engagement_participant_id=79401,
                collection_date=date(2026, 10, 5),
                relation=BloodBookingRelation.primary.value,
                status=BloodBookingStatus.cancelled.value,
                booking_id="cancelled-old",
                collected_at=_ist_collected_at(date(2026, 10, 5)),
            ),
            ParticipantBloodBooking(
                engagement_participant_id=79401,
                collection_date=TODAY,
                relation=BloodBookingRelation.primary.value,
                status=BloodBookingStatus.active.value,
                booking_id="rebooked",
                collected_at=_ist_collected_at(TODAY),
            ),
        ]
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/engagements/79104/booking-summary",
        headers=_auth_header(7914),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["today_expected_booking_count"] == 1
    assert data["today_pending_booking_count"] == 0
    assert data["total_booking_count"] == 1
    assert data["today_booking_count"] == 1
    assert data["pending_booking_count"] == 1


@pytest.mark.asyncio
async def test_booking_summary_walkin_collected_today_does_not_inflate_expected(
    async_client, test_db_session, freeze_ist_today
):
    await seed_employee(test_db_session, employee_id=7915)
    await _seed_engagement(test_db_session, engagement_id=79105, type_code="booking_summary_walkin")

    await _add_participant_booking(
        test_db_session,
        engagement_id=79105,
        user_id=79501,
        engagement_participant_id=79501,
        collection_date=TODAY,
        status=BloodBookingStatus.active,
        booking_id="scheduled-today",
        collected_at=_ist_collected_at(TODAY),
    )
    await _add_participant_booking(
        test_db_session,
        engagement_id=79105,
        user_id=79502,
        engagement_participant_id=79502,
        collection_date=date(2026, 10, 7),
        status=BloodBookingStatus.active,
        booking_id="walkin-from-tomorrow",
        collected_at=_ist_collected_at(TODAY),
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/engagements/79105/booking-summary",
        headers=_auth_header(7915),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["today_expected_booking_count"] == 1
    assert data["today_booking_count"] == 2
    assert data["today_pending_booking_count"] == 0
