"""E2E tests for POST /users/public/family-onboard."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.modules.users.family_onboard_helpers import (
    family_onboard_start_payload,
    seed_family_onboard_platform_defaults,
)


@pytest.mark.asyncio
async def test_family_onboard_start_creates_session_and_unpaid_enrollments(
    async_client,
    test_db_session,
):
    await seed_family_onboard_platform_defaults(test_db_session)

    response = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["payment_required"] is True
    assert data["family_onboard_id"]
    assert data["booker_user_id"]
    assert data["otp_session_id"]
    assert len(data["members"]) == 1

    booker_id = data["booker_user_id"]
    member = data["members"][0]

    booker_row = (
        await test_db_session.execute(
            text("SELECT parent_id FROM users WHERE user_id = :uid"),
            {"uid": booker_id},
        )
    ).first()
    assert booker_row.parent_id is None

    member_row = (
        await test_db_session.execute(
            text("SELECT parent_id, relationship FROM users WHERE user_id = :uid"),
            {"uid": member["user_id"]},
        )
    ).first()
    assert member_row.parent_id == booker_id
    assert str(member_row.relationship) in {"child", "CHILD"} or member_row.relationship == "child"

    participant = (
        await test_db_session.execute(
            text(
                "SELECT booked_by_user_id, paid FROM engagement_participants "
                "WHERE engagement_participant_id = :pid"
            ),
            {"pid": member["engagement_participant_id"]},
        )
    ).first()
    assert participant.booked_by_user_id == booker_id
    assert participant.paid is False

    engagement = (
        await test_db_session.execute(
            text("SELECT payment_type, organization_id FROM engagements WHERE engagement_id = :eid"),
            {"eid": member["engagement_id"]},
        )
    ).first()
    assert engagement.organization_id is None
    assert str(engagement.payment_type) in {"paid_by_patient", "EngagementPaymentType.paid_by_patient"}

    session_row = (
        await test_db_session.execute(
            text("SELECT status, booker_user_id FROM family_onboards WHERE family_onboard_id = :sid"),
            {"sid": data["family_onboard_id"]},
        )
    ).first()
    assert session_row is not None
    assert session_row.booker_user_id == booker_id
    assert session_row.status == "pending_payment"

    instance_count = (
        await test_db_session.execute(
            text(
                "SELECT COUNT(*) AS c FROM assessment_instances WHERE user_id = :uid AND engagement_id = :eid"
            ),
            {"uid": member["user_id"], "eid": member["engagement_id"]},
        )
    ).scalar()
    assert int(instance_count or 0) == 0


@pytest.mark.asyncio
async def test_family_onboard_start_reuses_sub_profile(async_client, test_db_session):
    await seed_family_onboard_platform_defaults(test_db_session)
    payload = family_onboard_start_payload(member_phone="9000100099")

    first = await async_client.post("/users/public/family-onboard", json=payload)
    assert first.status_code == 200
    first_member_id = first.json()["data"]["members"][0]["user_id"]
    assert first.json()["data"]["members"][0]["sub_profile_created"] is True

    second = await async_client.post("/users/public/family-onboard", json=payload)
    assert second.status_code == 200
    second_member_id = second.json()["data"]["members"][0]["user_id"]
    assert second_member_id == first_member_id
    assert second.json()["data"]["members"][0]["sub_profile_created"] is False
