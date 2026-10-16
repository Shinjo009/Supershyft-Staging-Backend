"""Admin PATCH participant blood bookings (collected_at corrections)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from modules.engagements.blood_booking_enums import BloodBookingStatus
from modules.engagements.models import ParticipantBloodBooking
from tests.helpers.auth import employee_auth_header, seed_employee
from tests.modules.engagements.test_booking_summary import (
    TODAY,
    _add_participant_booking,
    _seed_engagement,
    freeze_ist_today,
)


def _auth_header(employee_id: int) -> dict[str, str]:
    return employee_auth_header(employee_id)


@pytest.mark.asyncio
async def test_patch_blood_booking_collected_at_updates_summary(
    async_client, test_db_session, freeze_ist_today
):
    await seed_employee(test_db_session, employee_id=7920)
    engagement_id = 79200
    user_id = 792001
    ep_id = 792001
    await _seed_engagement(test_db_session, engagement_id=engagement_id, type_code="blood_admin_patch")
    await _add_participant_booking(
        test_db_session,
        engagement_id=engagement_id,
        user_id=user_id,
        engagement_participant_id=ep_id,
        collection_date=TODAY,
        status=BloodBookingStatus.active,
        booking_id="manual-booking-1",
        collected_at=None,
    )
    await test_db_session.commit()

    blood_row = (
        await test_db_session.execute(
            select(ParticipantBloodBooking).where(
                ParticipantBloodBooking.engagement_participant_id == ep_id
            )
        )
    ).scalars().one()

    collected_iso = datetime(
        TODAY.year, TODAY.month, TODAY.day, 7, 30, tzinfo=timezone.utc
    ).isoformat()

    patch_res = await async_client.patch(
        f"/engagements/{engagement_id}/participants/{user_id}/blood-bookings/{blood_row.id}",
        json={"collected_at": collected_iso},
        headers=_auth_header(7920),
    )
    assert patch_res.status_code == 200, patch_res.text
    patched = patch_res.json()["data"]
    assert patched["collected_at"] is not None

    summary_res = await async_client.get(
        f"/engagements/{engagement_id}/booking-summary",
        headers=_auth_header(7920),
    )
    assert summary_res.status_code == 200, summary_res.text
    summary = summary_res.json()["data"]
    assert summary["today_booking_count"] == 1
    assert summary["total_booking_count"] == 1


@pytest.mark.asyncio
async def test_patch_blood_booking_clear_collected_at(async_client, test_db_session, freeze_ist_today):
    await seed_employee(test_db_session, employee_id=7921)
    engagement_id = 79201
    user_id = 792011
    ep_id = 792011
    await _seed_engagement(test_db_session, engagement_id=engagement_id, type_code="blood_admin_clear")
    await _add_participant_booking(
        test_db_session,
        engagement_id=engagement_id,
        user_id=user_id,
        engagement_participant_id=ep_id,
        collection_date=TODAY,
        status=BloodBookingStatus.active,
        booking_id="manual-booking-2",
        collected_at=datetime(TODAY.year, TODAY.month, TODAY.day, 6, 0, tzinfo=timezone.utc),
    )
    await test_db_session.commit()

    blood_row = (
        await test_db_session.execute(
            select(ParticipantBloodBooking).where(
                ParticipantBloodBooking.engagement_participant_id == ep_id
            )
        )
    ).scalars().one()

    patch_res = await async_client.patch(
        f"/engagements/{engagement_id}/participants/{user_id}/blood-bookings/{blood_row.id}",
        json={"collected_at": None},
        headers=_auth_header(7921),
    )
    assert patch_res.status_code == 200, patch_res.text
    assert patch_res.json()["data"]["collected_at"] is None
