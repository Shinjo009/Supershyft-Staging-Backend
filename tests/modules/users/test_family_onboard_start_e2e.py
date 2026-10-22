"""E2E tests for POST /users/public/family-onboard."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.modules.users.family_onboard_helpers import (
    engagement_status_is,
    family_onboard_start_payload,
    seed_family_onboard_platform_defaults,
    seed_primary_user,
    seed_subprofile_user,
)


def _relationship_value(raw: object) -> str:
    return str(raw).strip().lower().split(".")[-1]


@pytest.mark.asyncio
async def test_family_onboard_start_creates_unpaid_enrollments(
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
    assert _relationship_value(member_row.relationship) == "child"

    participant = (
        await test_db_session.execute(
            text(
                "SELECT booked_by_user_id, paid, booker_relation FROM engagement_participants "
                "WHERE engagement_participant_id = :pid"
            ),
            {"pid": member["engagement_participant_id"]},
        )
    ).first()
    assert participant.booked_by_user_id == booker_id
    assert participant.paid is False
    assert _relationship_value(participant.booker_relation) == "child"

    engagement = (
        await test_db_session.execute(
            text(
                "SELECT payment_type, organization_id, status FROM engagements "
                "WHERE engagement_id = :eid"
            ),
            {"eid": member["engagement_id"]},
        )
    ).first()
    assert engagement.organization_id is None
    assert str(engagement.payment_type) in {"paid_by_patient", "EngagementPaymentType.paid_by_patient"}
    assert engagement_status_is(engagement.status, "draft")

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
    first_pid = first.json()["data"]["members"][0]["engagement_participant_id"]
    assert first.json()["data"]["members"][0]["sub_profile_created"] is True

    second = await async_client.post("/users/public/family-onboard", json=payload)
    assert second.status_code == 200
    second_member_id = second.json()["data"]["members"][0]["user_id"]
    second_pid = second.json()["data"]["members"][0]["engagement_participant_id"]
    assert second_member_id == first_member_id
    assert second.json()["data"]["members"][0]["sub_profile_created"] is False

    for pid in (first_pid, second_pid):
        row = (
            await test_db_session.execute(
                text("SELECT booker_relation FROM engagement_participants WHERE engagement_participant_id = :pid"),
                {"pid": pid},
            )
        ).first()
        assert _relationship_value(row.booker_relation) == "child"

    member_row = (
        await test_db_session.execute(
            text("SELECT relationship FROM users WHERE user_id = :uid"),
            {"uid": first_member_id},
        )
    ).first()
    assert _relationship_value(member_row.relationship) == "child"


@pytest.mark.asyncio
async def test_family_onboard_start_reuses_existing_primary_booker(async_client, test_db_session):
    await seed_family_onboard_platform_defaults(test_db_session)
    await seed_primary_user(
        test_db_session,
        user_id=91001,
        phone="9000101001",
        email="existing.booker@example.com",
    )

    response = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(
            booker_phone="9000101001",
            booker_email="existing.booker@example.com",
            member_phone="9000101002",
        ),
    )
    assert response.status_code == 200
    assert response.json()["data"]["booker_user_id"] == 91001

    booker_row = (
        await test_db_session.execute(
            text("SELECT parent_id FROM users WHERE user_id = 91001"),
        )
    ).first()
    assert booker_row.parent_id is None


@pytest.mark.asyncio
async def test_family_onboard_start_rejects_subprofile_booker(async_client, test_db_session):
    await seed_family_onboard_platform_defaults(test_db_session)
    await seed_primary_user(
        test_db_session,
        user_id=91010,
        phone="9000101010",
        email="parent.only@example.com",
    )
    await seed_subprofile_user(
        test_db_session,
        user_id=91011,
        parent_id=91010,
        phone="9000101011",
        email="sub.booker@example.com",
    )

    before_count = (
        await test_db_session.execute(text("SELECT COUNT(*) FROM engagement_participants"))
    ).scalar()

    response = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(
            booker_phone="9000101011",
            booker_email="sub.booker@example.com",
            member_phone="9000101012",
        ),
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("error_code") == "INVALID_INPUT"
    assert "primary account" in (body.get("message") or "").lower()

    after_count = (
        await test_db_session.execute(text("SELECT COUNT(*) FROM engagement_participants"))
    ).scalar()
    assert int(after_count or 0) == int(before_count or 0)


@pytest.mark.asyncio
async def test_family_onboard_start_creates_subprofile_and_writes_both_relations(
    async_client,
    test_db_session,
):
    await seed_family_onboard_platform_defaults(test_db_session)
    payload = family_onboard_start_payload(
        member_phone="9000101101",
        member_relation="parent",
    )

    response = await async_client.post("/users/public/family-onboard", json=payload)
    assert response.status_code == 200
    data = response.json()["data"]
    member = data["members"][0]
    assert member["sub_profile_created"] is True

    member_row = (
        await test_db_session.execute(
            text("SELECT parent_id, relationship FROM users WHERE user_id = :uid"),
            {"uid": member["user_id"]},
        )
    ).first()
    assert member_row.parent_id == data["booker_user_id"]
    assert _relationship_value(member_row.relationship) == "parent"

    participant = (
        await test_db_session.execute(
            text(
                "SELECT booked_by_user_id, paid, booker_relation FROM engagement_participants "
                "WHERE engagement_participant_id = :pid"
            ),
            {"pid": member["engagement_participant_id"]},
        )
    ).first()
    assert participant.booked_by_user_id == data["booker_user_id"]
    assert participant.paid is False
    assert _relationship_value(participant.booker_relation) == "parent"


@pytest.mark.asyncio
async def test_family_onboard_start_enrolls_existing_primary_member(async_client, test_db_session):
    await seed_family_onboard_platform_defaults(test_db_session)
    await seed_primary_user(
        test_db_session,
        user_id=91020,
        phone="9000101020",
        email="existing.member@example.com",
        relationship="self",
    )

    response = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(
            member_phone="9000101020",
            member_relation="sibling",
            booker_email="new.booker.for.member@example.com",
        ),
    )
    assert response.status_code == 200
    member = response.json()["data"]["members"][0]
    assert member["sub_profile_created"] is False
    assert member["user_id"] == 91020

    member_row = (
        await test_db_session.execute(
            text("SELECT parent_id, relationship FROM users WHERE user_id = 91020"),
        )
    ).first()
    assert member_row.parent_id is None
    assert _relationship_value(member_row.relationship) == "self"

    participant = (
        await test_db_session.execute(
            text("SELECT booker_relation FROM engagement_participants WHERE engagement_participant_id = :pid"),
            {"pid": member["engagement_participant_id"]},
        )
    ).first()
    assert _relationship_value(participant.booker_relation) == "sibling"


@pytest.mark.asyncio
async def test_family_onboard_start_enrolls_foreign_subprofile_member(async_client, test_db_session):
    await seed_family_onboard_platform_defaults(test_db_session)
    await seed_primary_user(
        test_db_session,
        user_id=91030,
        phone="9000101030",
        email="other.parent@example.com",
    )
    await seed_subprofile_user(
        test_db_session,
        user_id=91031,
        parent_id=91030,
        phone="9000101031",
        email="other.child@example.com",
        relationship="child",
    )

    response = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(
            member_phone="9000101031",
            member_relation="sibling",
            booker_email="foreign.booker@example.com",
        ),
    )
    assert response.status_code == 200
    member = response.json()["data"]["members"][0]
    assert member["sub_profile_created"] is False
    assert member["user_id"] == 91031

    member_row = (
        await test_db_session.execute(
            text("SELECT parent_id, relationship FROM users WHERE user_id = 91031"),
        )
    ).first()
    assert member_row.parent_id == 91030
    assert _relationship_value(member_row.relationship) == "child"

    participant = (
        await test_db_session.execute(
            text("SELECT booker_relation FROM engagement_participants WHERE engagement_participant_id = :pid"),
            {"pid": member["engagement_participant_id"]},
        )
    ).first()
    assert _relationship_value(participant.booker_relation) == "sibling"


@pytest.mark.asyncio
async def test_family_onboard_start_updates_existing_booker_email(async_client, test_db_session):
    await seed_family_onboard_platform_defaults(test_db_session)
    await seed_primary_user(
        test_db_session,
        user_id=91040,
        phone="9000101040",
        email="old.booker@example.com",
    )

    response = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(
            booker_phone="9000101040",
            booker_email="updated.booker@example.com",
            member_phone="9000101041",
        ),
    )
    assert response.status_code == 200
    assert response.json()["data"]["booker_user_id"] == 91040

    row = (
        await test_db_session.execute(
            text("SELECT email FROM users WHERE user_id = 91040"),
        )
    ).first()
    assert row.email == "updated.booker@example.com"


@pytest.mark.asyncio
async def test_family_onboard_start_updates_existing_own_child_member_email(
    async_client, test_db_session
):
    await seed_family_onboard_platform_defaults(test_db_session)
    await seed_primary_user(
        test_db_session,
        user_id=91050,
        phone="9000101050",
        email="parent.for.child@example.com",
    )
    await seed_subprofile_user(
        test_db_session,
        user_id=91051,
        parent_id=91050,
        phone="9000101051",
        email="old.child@example.com",
    )

    response = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(
            booker_phone="9000101050",
            booker_email="parent.for.child@example.com",
            member_phone="9000101051",
            member_email="new.child@example.com",
        ),
    )
    assert response.status_code == 200
    assert response.json()["data"]["members"][0]["user_id"] == 91051

    row = (
        await test_db_session.execute(
            text("SELECT email FROM users WHERE user_id = 91051"),
        )
    ).first()
    assert row.email == "new.child@example.com"


@pytest.mark.asyncio
async def test_family_onboard_start_updates_existing_primary_member_email(
    async_client, test_db_session
):
    await seed_family_onboard_platform_defaults(test_db_session)
    await seed_primary_user(
        test_db_session,
        user_id=91060,
        phone="9000101060",
        email="old.member@example.com",
    )

    response = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(
            member_phone="9000101060",
            member_email="fresh.member@example.com",
        ),
    )
    assert response.status_code == 200
    assert response.json()["data"]["members"][0]["user_id"] == 91060

    row = (
        await test_db_session.execute(
            text("SELECT email FROM users WHERE user_id = 91060"),
        )
    ).first()
    assert row.email == "fresh.member@example.com"


@pytest.mark.asyncio
async def test_family_onboard_start_rejects_booker_email_owned_by_other_user(
    async_client, test_db_session
):
    await seed_family_onboard_platform_defaults(test_db_session)
    await seed_primary_user(
        test_db_session,
        user_id=91070,
        phone="9000101070",
        email="booker.old@example.com",
    )
    await seed_primary_user(
        test_db_session,
        user_id=91071,
        phone="9000101071",
        email="taken.by.other@example.com",
    )

    before_count = (
        await test_db_session.execute(text("SELECT COUNT(*) FROM engagement_participants"))
    ).scalar()

    response = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(
            booker_phone="9000101070",
            booker_email="taken.by.other@example.com",
            member_phone="9000101072",
        ),
    )
    assert response.status_code == 409
    assert response.json().get("error_code") == "CONFLICT"

    after_count = (
        await test_db_session.execute(text("SELECT COUNT(*) FROM engagement_participants"))
    ).scalar()
    assert int(after_count or 0) == int(before_count or 0)

    row = (
        await test_db_session.execute(
            text("SELECT email FROM users WHERE user_id = 91070"),
        )
    ).first()
    assert row.email == "booker.old@example.com"


@pytest.mark.asyncio
async def test_family_onboard_start_booker_reclaims_email_from_own_sub(
    async_client, test_db_session
):
    await seed_family_onboard_platform_defaults(test_db_session)
    await seed_primary_user(
        test_db_session,
        user_id=91080,
        phone="9000101080",
        email="parent.reclaim@example.com",
    )
    await seed_subprofile_user(
        test_db_session,
        user_id=91081,
        parent_id=91080,
        phone="9000101081",
        email="reclaim.target@example.com",
    )

    response = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(
            booker_phone="9000101080",
            booker_email="reclaim.target@example.com",
            member_phone="9000101082",
        ),
    )
    assert response.status_code == 200
    assert response.json()["data"]["booker_user_id"] == 91080

    booker_row = (
        await test_db_session.execute(
            text("SELECT email FROM users WHERE user_id = 91080"),
        )
    ).first()
    assert booker_row.email == "reclaim.target@example.com"

    sub_row = (
        await test_db_session.execute(
            text("SELECT email FROM users WHERE user_id = 91081"),
        )
    ).first()
    assert sub_row.email.startswith("reclaim.target+")
    assert sub_row.email.endswith("@example.com")


@pytest.mark.asyncio
async def test_family_onboard_start_leaves_member_email_when_omitted(
    async_client, test_db_session
):
    await seed_family_onboard_platform_defaults(test_db_session)
    await seed_primary_user(
        test_db_session,
        user_id=91090,
        phone="9000101090",
        email="booker.omit@example.com",
    )
    await seed_subprofile_user(
        test_db_session,
        user_id=91091,
        parent_id=91090,
        phone="9000101091",
        email="keep.this@example.com",
    )

    response = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(
            booker_phone="9000101090",
            booker_email="booker.omit@example.com",
            member_phone="9000101091",
        ),
    )
    assert response.status_code == 200

    row = (
        await test_db_session.execute(
            text("SELECT email FROM users WHERE user_id = 91091"),
        )
    ).first()
    assert row.email == "keep.this@example.com"
