"""Participant admin lists return newest enrollments first (LIFO)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from modules.engagements.repository import EngagementsRepository


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
            "city, slot_duration, start_date, end_date, status, payment_type"
            ") VALUES ("
            ":eid, :ename, :ecode, :etype, 'BLR', 20, '2026-01-01', '2026-01-02', 3, :pt"
            ") ON CONFLICT (engagement_id) DO NOTHING"
        ),
        {
            "eid": engagement_id,
            "ename": code,
            "ecode": code,
            "etype": int(type_id),
            "pt": "paid_by_patient",
        },
    )


async def _seed_participant(
    test_db_session,
    *,
    ep_id: int,
    engagement_id: int,
    user_id: int,
) -> None:
    await _seed_user(test_db_session, user_id)
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_participants "
            "(engagement_participant_id, engagement_id, user_id, booked_by_user_id, paid) "
            "VALUES (:ep, :eid, :uid, :uid, false) "
            "ON CONFLICT (engagement_participant_id) DO NOTHING"
        ),
        {"ep": ep_id, "eid": engagement_id, "uid": user_id},
    )


@pytest.mark.asyncio
async def test_list_participants_by_engagement_id_is_newest_first(test_db_session):
    engagement_id = 991001
    await _seed_engagement(test_db_session, engagement_id, "LIFO991001")
    await _seed_participant(
        test_db_session, ep_id=991301, engagement_id=engagement_id, user_id=991201
    )
    await _seed_participant(
        test_db_session, ep_id=991302, engagement_id=engagement_id, user_id=991202
    )
    await test_db_session.commit()

    repo = EngagementsRepository()
    rows = await repo.list_participants_by_engagement_id(
        test_db_session,
        engagement_id=engagement_id,
        page=1,
        limit=10,
    )
    assert len(rows) >= 2
    ids = [int(row[0]) for row in rows]
    assert ids == sorted(ids, reverse=True)
    assert ids[0] == 991302
