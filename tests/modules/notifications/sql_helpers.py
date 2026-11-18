"""SQL helpers for notification module tests."""

from __future__ import annotations

from datetime import date, time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.column_types import STATUS_BLOOD_BOOKING, STATUS_ENGAGEMENT


def engagement_status_code(label: str) -> int:
    return int(STATUS_ENGAGEMENT[label])


async def insert_participant_blood_slot(
    session: AsyncSession,
    *,
    engagement_id: int,
    user_id: int,
    collection_date: date | str,
    slot_start_time: time | str | None,
) -> int:
    if isinstance(collection_date, str):
        collection_date = date.fromisoformat(collection_date)
    coll_time: time | None
    if slot_start_time is None:
        coll_time = None
    elif isinstance(slot_start_time, str):
        coll_time = time.fromisoformat(slot_start_time)
    else:
        coll_time = slot_start_time

    ep_id = (
        await session.execute(
            text(
                "INSERT INTO engagement_participants "
                "(engagement_id, user_id, booked_by_user_id) "
                "VALUES (:eid, :uid, :uid) "
                "RETURNING engagement_participant_id"
            ),
            {"eid": engagement_id, "uid": user_id},
        )
    ).scalar_one()
    await session.execute(
        text(
            "INSERT INTO participant_blood_bookings "
            "(engagement_participant_id, collection_date, collection_time, status) "
            "VALUES (:epid, :cd, :ct, :st)"
        ),
        {
            "epid": ep_id,
            "cd": collection_date,
            "ct": coll_time,
            "st": STATUS_BLOOD_BOOKING["active"],
        },
    )
    return int(ep_id)