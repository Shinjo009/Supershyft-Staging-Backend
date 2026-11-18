"""Tests for camp progress-report and day-wise-summary endpoints."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from modules.engagements.blood_booking_enums import BloodBookingRelation, BloodBookingStatus
from modules.engagements.models import (
    Engagement,
    EngagementParticipant,
    EngagementSlotInfo,
    ParticipantBloodBooking,
)
from modules.experts.models import ConsultationBooking
from modules.users.models import User
from tests.helpers.auth import employee_auth_header, seed_employee


DAY_A = date(2026, 11, 17)
DAY_B = date(2026, 11, 18)


def _auth_header(employee_id: int) -> dict[str, str]:
    return employee_auth_header(employee_id)


def _ist_collected_at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 6, 0, tzinfo=timezone.utc)


async def _seed_engagement(
    test_db_session,
    *,
    engagement_id: int,
    with_slots: bool = True,
):
    slot_detail_id = None
    if with_slots:
        slot_detail_id = engagement_id
        test_db_session.add(
            EngagementSlotInfo(
                slot_detail_id=slot_detail_id,
                slot_detail={
                    "blood_collection": {
                        "is_enable": True,
                        DAY_A.isoformat(): {"is_enable": True, "cabins": []},
                        DAY_B.isoformat(): {"is_enable": True, "cabins": []},
                    },
                    "consultation": {
                        "is_enable": True,
                        DAY_A.isoformat(): {"is_enable": True, "cabins": []},
                        DAY_B.isoformat(): {"is_enable": True, "cabins": []},
                    },
                },
            )
        )
        await test_db_session.flush()

    test_db_session.add(
        Engagement(
            engagement_id=engagement_id,
            engagement_code=f"CAMP{engagement_id}",
            assessment_package_id=1,
            diagnostic_package_id=1,
            slot_duration=20,
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 30),
            status="running",
            organization_id=None,
            slot_detail_id=slot_detail_id,
            blood_collection_type="camp_collection",
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


async def _add_participant(
    test_db_session,
    *,
    engagement_id: int,
    user_id: int,
    engagement_participant_id: int,
    collection_date: date | None = None,
    booking_id: str | None = None,
    collected_at: datetime | None = None,
    want_consult: bool = False,
    consult_date: date | None = None,
    consult_done: bool = False,
    consult_done_at: datetime | None = None,
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
    if collection_date is not None or collected_at is not None or booking_id is not None:
        test_db_session.add(
            ParticipantBloodBooking(
                engagement_participant_id=engagement_participant_id,
                collection_date=collection_date,
                relation=BloodBookingRelation.primary.value,
                status=BloodBookingStatus.active.value,
                booking_id=booking_id,
                collected_at=collected_at,
            )
        )
    if want_consult or consult_done:
        test_db_session.add(
            ConsultationBooking(
                engagement_participant_id=engagement_participant_id,
                expert_type="nutritionist",
                want=want_consult,
                consultation_date=consult_date,
                done=consult_done,
                consultation_done_at=consult_done_at,
            )
        )


@pytest.mark.asyncio
async def test_progress_report_counts(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8801)
    await _seed_engagement(test_db_session, engagement_id=88001, with_slots=False)

    await _add_participant(
        test_db_session,
        engagement_id=88001,
        user_id=88011,
        engagement_participant_id=880101,
        collection_date=DAY_A,
        booking_id="B1",
        collected_at=_ist_collected_at(DAY_A),
        want_consult=True,
        consult_date=DAY_A,
        consult_done=True,
        consult_done_at=_ist_collected_at(DAY_A),
    )
    await _add_participant(
        test_db_session,
        engagement_id=88001,
        user_id=88012,
        engagement_participant_id=880102,
        collection_date=DAY_B,
    )
    await test_db_session.commit()

    res = await async_client.get(
        "/engagements/88001/progress-report",
        headers=_auth_header(8801),
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["total_registered"] == 2
    assert data["blood_collected"] == 1
    assert data["consultation_done"] == 1
    assert data["questionnaire_filled"] == 0
    assert data["blood_report_sent"] == 0
    assert data["bio_ai_report_sent"] == 0


@pytest.mark.asyncio
async def test_progress_report_blood_collected_requires_booking_id(
    async_client, test_db_session
):
    await seed_employee(test_db_session, employee_id=8804)
    await _seed_engagement(test_db_session, engagement_id=88004, with_slots=False)

    await _add_participant(
        test_db_session,
        engagement_id=88004,
        user_id=88041,
        engagement_participant_id=880401,
        collection_date=DAY_A,
        booking_id=None,
        collected_at=_ist_collected_at(DAY_A),
    )
    await test_db_session.commit()

    res = await async_client.get(
        "/engagements/88004/progress-report",
        headers=_auth_header(8804),
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["total_registered"] == 1
    assert data["blood_collected"] == 0


@pytest.mark.asyncio
async def test_day_wise_summary_blood_and_consultation(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8802)
    await _seed_engagement(test_db_session, engagement_id=88002, with_slots=True)

    await _add_participant(
        test_db_session,
        engagement_id=88002,
        user_id=88021,
        engagement_participant_id=880201,
        collection_date=DAY_A,
        booking_id="B2",
        collected_at=_ist_collected_at(DAY_A),
        want_consult=True,
        consult_date=DAY_A,
        consult_done=True,
        consult_done_at=_ist_collected_at(DAY_A),
    )
    await _add_participant(
        test_db_session,
        engagement_id=88002,
        user_id=88022,
        engagement_participant_id=880202,
        collection_date=DAY_A,
        want_consult=True,
        consult_date=DAY_B,
    )
    await test_db_session.commit()

    res = await async_client.get(
        "/engagements/88002/day-wise-summary",
        headers=_auth_header(8802),
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["blood_collection_dates"] == [DAY_A.isoformat(), DAY_B.isoformat()]
    assert data["consultation_dates"] == [DAY_A.isoformat(), DAY_B.isoformat()]

    blood_a = data["blood_collection"][DAY_A.isoformat()]
    assert blood_a["expected_collection"] == 2
    assert blood_a["sample_collected"] == 1

    consult_a = data["consultation"][DAY_A.isoformat()]
    assert consult_a["consultation_want"] == 1
    assert consult_a["consultation_done"] == 1

    consult_b = data["consultation"][DAY_B.isoformat()]
    assert consult_b["consultation_want"] == 1
    assert consult_b["consultation_done"] == 0


@pytest.mark.asyncio
async def test_day_wise_summary_date_filter(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8803)
    await _seed_engagement(test_db_session, engagement_id=88003, with_slots=True)
    await test_db_session.commit()

    res = await async_client.get(
        f"/engagements/88003/day-wise-summary?section=blood_collection&date={DAY_A.isoformat()}",
        headers=_auth_header(8803),
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert DAY_A.isoformat() in data["blood_collection"]
    assert data["consultation"] == {}
