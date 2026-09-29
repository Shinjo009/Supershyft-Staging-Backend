from __future__ import annotations

from datetime import date, time

import pytest
from sqlalchemy import text

from core.exceptions import AppError
from modules.engagements.blood_booking_id_validation import ensure_active_booking_id_available
from modules.engagements.repository import EngagementsRepository
from modules.engagements.schemas import EngagementParticipantUpdateRequest
from modules.engagements.service import EngagementsService
from modules.employee.models import EmployeeRole
from modules.employee.service import EmployeeContext
from tests.helpers.auth import employee_auth_header, seed_employee


async def _seed_user(test_db_session, user_id: int) -> None:
    await test_db_session.execute(
        text(
            "INSERT INTO users (user_id, age, phone, status) "
            "VALUES (:uid, 30, :phone, 1) ON CONFLICT (user_id) DO NOTHING"
        ),
        {"uid": user_id, "phone": f"{user_id:010d}"},
    )


async def _seed_engagement(test_db_session, engagement_id: int, code: str) -> None:
    type_id = (
        await test_db_session.execute(
            text("SELECT id FROM engagement_types WHERE code = 'bio_ai' LIMIT 1")
        )
    ).scalar_one()
    await test_db_session.execute(
        text(
            "INSERT INTO engagements ("
            "engagement_id, engagement_name, engagement_code, engagement_type, "
            "city, slot_duration, start_date, end_date, status"
            ") VALUES ("
            ":eid, :ename, :ecode, :etype, 'BLR', 20, '2026-01-01', '2026-01-02', 3"
            ") ON CONFLICT (engagement_id) DO NOTHING"
        ),
        {"eid": engagement_id, "ename": code, "ecode": code, "etype": int(type_id)},
    )


async def _seed_participant(test_db_session, *, ep_id: int, engagement_id: int, user_id: int) -> None:
    await _seed_user(test_db_session, user_id)
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_participants "
            "(engagement_participant_id, engagement_id, user_id, booked_by_user_id) "
            "VALUES (:ep, :eid, :uid, :uid) ON CONFLICT (engagement_participant_id) DO NOTHING"
        ),
        {"ep": ep_id, "eid": engagement_id, "uid": user_id},
    )


@pytest.mark.asyncio
async def test_cancelled_row_does_not_block_active_booking_id_reuse(test_db_session):
    await _seed_engagement(test_db_session, 8800, "BK8800")
    await _seed_participant(test_db_session, ep_id=88001, engagement_id=8800, user_id=8801)
    await test_db_session.execute(
        text(
            "INSERT INTO participant_blood_bookings "
            "(id, engagement_participant_id, relation, status, booking_id) "
            "VALUES (88011, 88001, 'primary', 3, '19659386363') "
            "ON CONFLICT (id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO participant_blood_bookings "
            "(id, engagement_participant_id, relation, status, collection_date, collection_time) "
            "VALUES (88012, 88001, 'primary', 1, '2026-09-19', '06:00:00') "
            "ON CONFLICT (id) DO NOTHING"
        )
    )
    await test_db_session.commit()

    await ensure_active_booking_id_available(
        test_db_session,
        booking_id="19659386363",
        exclude_pbb_id=88012,
    )


@pytest.mark.asyncio
async def test_active_duplicate_booking_id_raises_409(test_db_session):
    await _seed_engagement(test_db_session, 8801, "BK8801")
    await _seed_participant(test_db_session, ep_id=88002, engagement_id=8801, user_id=8802)
    await _seed_participant(test_db_session, ep_id=88003, engagement_id=8801, user_id=8803)
    await test_db_session.execute(
        text(
            "UPDATE users SET first_name = 'A', last_name = 'One' WHERE user_id = 8802"
        )
    )
    await test_db_session.execute(
        text(
            "UPDATE users SET first_name = 'B', last_name = 'Two' WHERE user_id = 8803"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO participant_blood_bookings "
            "(id, engagement_participant_id, relation, status, booking_id) "
            "VALUES (88021, 88002, 'primary', 1, 'BOOK-DUP-1') ON CONFLICT (id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO participant_blood_bookings "
            "(id, engagement_participant_id, relation, status) "
            "VALUES (88031, 88003, 'primary', 1) ON CONFLICT (id) DO NOTHING"
        )
    )
    await test_db_session.commit()

    with pytest.raises(AppError) as exc:
        await ensure_active_booking_id_available(
            test_db_session,
            booking_id="BOOK-DUP-1",
            exclude_pbb_id=88031,
        )
    assert exc.value.status_code == 409
    assert exc.value.error_code == "BOOKING_ID_EXISTS"


@pytest.mark.asyncio
async def test_patch_participant_booking_id_succeeds_when_only_cancelled_has_id(
    async_client, test_db_session
):
    await seed_employee(test_db_session, employee_id=41, role="admin")
    await _seed_engagement(test_db_session, 8810, "BK8810")
    await _seed_participant(test_db_session, ep_id=88101, engagement_id=8810, user_id=8811)
    await test_db_session.execute(
        text(
            "INSERT INTO participant_blood_bookings "
            "(id, engagement_participant_id, relation, status, booking_id, collection_date) "
            "VALUES (88111, 88101, 'primary', 3, '19659386363', '2026-09-18') "
            "ON CONFLICT (id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO participant_blood_bookings "
            "(id, engagement_participant_id, relation, status, collection_date, collection_time) "
            "VALUES (88112, 88101, 'primary', 1, '2026-09-19', '06:00:00') "
            "ON CONFLICT (id) DO NOTHING"
        )
    )
    await test_db_session.commit()

    response = await async_client.patch(
        "/engagements/8810/participants/8811",
        json={"booking_id": "19659386363"},
        headers=employee_auth_header(41),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["booking_id"] == "19659386363"

    active_bid = (
        await test_db_session.execute(
            text(
                "SELECT booking_id FROM participant_blood_bookings "
                "WHERE id = 88112 AND status = 1"
            )
        )
    ).scalar_one()
    assert active_bid == "19659386363"


@pytest.mark.asyncio
async def test_update_participant_for_employee_validates_booking_id(test_db_session):
    await seed_employee(test_db_session, employee_id=42, role="admin")
    await _seed_engagement(test_db_session, 8820, "BK8820")
    await _seed_participant(test_db_session, ep_id=88201, engagement_id=8820, user_id=8821)
    await _seed_participant(test_db_session, ep_id=88202, engagement_id=8820, user_id=8822)
    await test_db_session.execute(
        text(
            "INSERT INTO participant_blood_bookings "
            "(id, engagement_participant_id, relation, status, booking_id) "
            "VALUES (88211, 88201, 'primary', 1, 'SHARED-ID') ON CONFLICT (id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO participant_blood_bookings "
            "(id, engagement_participant_id, relation, status) "
            "VALUES (88221, 88202, 'primary', 1) ON CONFLICT (id) DO NOTHING"
        )
    )
    await test_db_session.commit()

    service = EngagementsService(EngagementsRepository())
    employee = EmployeeContext(employee_id=42, role=EmployeeRole.admin)
    with pytest.raises(AppError) as exc:
        await service.update_participant_for_employee(
            test_db_session,
            employee=employee,
            engagement_id=8820,
            user_id=8822,
            payload=EngagementParticipantUpdateRequest(booking_id="SHARED-ID"),
            ip_address="127.0.0.1",
            user_agent="test",
            endpoint="/test",
        )
    assert exc.value.status_code == 409
