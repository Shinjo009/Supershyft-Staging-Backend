"""Tests for Metsights backfill of users.created_at."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from modules.users.backfill_created_at_from_metsights import (
    _parse_metsights_timestamp,
    backfill_users_created_at_from_metsights,
)
from sqlalchemy import update

from modules.users.models import User
from modules.users.repository import UsersRepository


def test_parse_metsights_timestamp_z_suffix():
    parsed = _parse_metsights_timestamp("2025-10-15T09:00:00Z")
    assert parsed == datetime(2025, 10, 15, 9, 0, 0, tzinfo=timezone.utc)


def test_parse_metsights_timestamp_offset():
    parsed = _parse_metsights_timestamp("2026-11-12T14:38:05.741814+05:30")
    assert parsed is not None
    assert parsed.utcoffset() is not None


@pytest.mark.asyncio
async def test_create_user_stamps_created_at(test_db_session):
    repo = UsersRepository()
    user = User(
        user_id=880001,
        age=30,
        phone="8800010001",
        status="active",
        metsights_profile_id="profile-880001",
    )
    created = await repo.create_user(test_db_session, user)
    await test_db_session.commit()
    assert created.created_at is not None
    assert created.updated_at is not None


async def _insert_user_without_created_at(session, *, user_id: int, phone: str, profile_id: str) -> None:
    user = User(
        user_id=user_id,
        age=30,
        phone=phone,
        status="active",
        metsights_profile_id=profile_id,
        created_at=None,
        updated_at=None,
    )
    session.add(user)
    await session.flush()
    # ORM/server_default may populate created_at on flush; prod rows are genuinely NULL.
    await session.execute(
        update(User).where(User.user_id == user_id).values(created_at=None, updated_at=None)
    )
    await session.flush()


@pytest.mark.asyncio
async def test_backfill_dry_run_no_write(test_db_session):
    repo = UsersRepository()
    await _insert_user_without_created_at(
        test_db_session,
        user_id=880002,
        phone="8800020002",
        profile_id="ms-profile-880002",
    )
    await test_db_session.commit()

    metsights = AsyncMock()
    metsights.get_profile_detail = AsyncMock(
        return_value={"created_at": "2025-03-06T17:15:39.363181+05:30"}
    )

    result = await backfill_users_created_at_from_metsights(
        test_db_session,
        metsights_service=metsights,
        users_repo=repo,
        dry_run=True,
        sleep_ms=0,
    )

    assert result["updated"] == 1
    assert result["dry_run"] is True
    refreshed = await repo.get_user_by_id(test_db_session, 880002)
    assert refreshed is not None
    assert refreshed.created_at is None


@pytest.mark.asyncio
async def test_backfill_apply_writes_created_at(test_db_session):
    repo = UsersRepository()
    await _insert_user_without_created_at(
        test_db_session,
        user_id=880003,
        phone="8800030003",
        profile_id="ms-profile-880003",
    )
    await test_db_session.commit()

    metsights = AsyncMock()
    metsights.get_profile_detail = AsyncMock(
        return_value={"created_at": "2025-12-11T16:30:27.961908+05:30"}
    )

    result = await backfill_users_created_at_from_metsights(
        test_db_session,
        metsights_service=metsights,
        users_repo=repo,
        dry_run=False,
        sleep_ms=0,
        batch_size=10,
    )
    await test_db_session.commit()

    assert result["updated"] == 1
    assert result["failed"] == 0
    refreshed = await repo.get_user_by_id(test_db_session, 880003)
    assert refreshed is not None
    assert refreshed.created_at is not None
    assert refreshed.created_at.year == 2025


@pytest.mark.asyncio
async def test_backfill_skip_missing_created_at_on_profile(test_db_session):
    repo = UsersRepository()
    await _insert_user_without_created_at(
        test_db_session,
        user_id=880004,
        phone="8800040004",
        profile_id="ms-profile-880004",
    )
    await test_db_session.commit()

    metsights = AsyncMock()
    metsights.get_profile_detail = AsyncMock(return_value={"id": "ms-profile-880004"})

    result = await backfill_users_created_at_from_metsights(
        test_db_session,
        metsights_service=metsights,
        users_repo=repo,
        dry_run=False,
        sleep_ms=0,
    )

    assert result["skipped"] == 1
    assert result["updated"] == 0


@pytest.mark.asyncio
async def test_backfill_failed_increments_on_api_error(test_db_session):
    repo = UsersRepository()
    await _insert_user_without_created_at(
        test_db_session,
        user_id=880005,
        phone="8800050005",
        profile_id="ms-profile-880005",
    )
    await test_db_session.commit()

    metsights = AsyncMock()
    metsights.get_profile_detail = AsyncMock(side_effect=RuntimeError("403 Forbidden"))

    result = await backfill_users_created_at_from_metsights(
        test_db_session,
        metsights_service=metsights,
        users_repo=repo,
        dry_run=False,
        sleep_ms=0,
    )

    assert result["failed"] == 1
    assert result["updated"] == 0