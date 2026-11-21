"""Tests for legacy DOB estimate backfill."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from modules.users.backfill_user_dob_estimates import backfill_user_dob_estimates
from modules.users.models import User


@pytest.mark.asyncio
async def test_backfill_dry_run_estimates_from_created_at_year(test_db_session):
    user = User(
        user_id=88001,
        phone="8800188001",
        age=25,
        date_of_birth=None,
        created_at=datetime(2020, 6, 1, tzinfo=timezone.utc),
        status="active",
    )
    test_db_session.add(user)
    await test_db_session.flush()

    result = await backfill_user_dob_estimates(
        test_db_session,
        dry_run=True,
        fallback_business_date=date(2026, 11, 21),
    )

    assert result["eligible_backfills"] >= 1
    assert result["applied_backfills"] == 0

    await backfill_user_dob_estimates(
        test_db_session,
        dry_run=False,
        fallback_business_date=date(2026, 11, 21),
    )
    await test_db_session.refresh(user)
    assert user.date_of_birth == date(1995, 1, 1)
    assert user.dob_provenance == "migration_estimated"