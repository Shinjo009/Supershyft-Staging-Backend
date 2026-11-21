"""Dry-run-first backfill: derive missing DOB from legacy age + created_at year."""

from __future__ import annotations

from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.dashboard.command_period import bound_calendar_date, command_today
from modules.users.age_policy import (
    AgePolicyValidationError,
    MAXIMUM_ACCOUNT_AGE,
    migration_estimate_dob,
)
from modules.users.models import User

IST = ZoneInfo("Asia/Kolkata")


async def backfill_user_dob_estimates(
    db: AsyncSession,
    *,
    dry_run: bool,
    batch_size: int = 500,
    user_id: int | None = None,
    fallback_business_date: date | None = None,
) -> dict[str, Any]:
    """Backfill nullable DOB rows that have a plausible stored age."""
    fallback_date = fallback_business_date or command_today()
    fallback_year = fallback_date.year

    query = (
        select(User)
        .where(User.date_of_birth.is_(None))
        .order_by(User.user_id.asc())
    )
    if user_id is not None:
        query = query.where(User.user_id == user_id)

    rows = list((await db.execute(query)).scalars().all())

    counts = {
        "scanned": len(rows),
        "preserved_existing_dob": 0,
        "eligible_backfills": 0,
        "applied_backfills": 0,
        "unknown_invalid_age": 0,
        "skipped_already_provenance": 0,
    }

    for user in rows:
        if user.date_of_birth is not None:
            counts["preserved_existing_dob"] += 1
            if user.dob_provenance is None:
                if not dry_run:
                    user.dob_provenance = "unknown"
            continue

        age = user.age
        if age is None or age < 1 or age > MAXIMUM_ACCOUNT_AGE:
            counts["unknown_invalid_age"] += 1
            continue

        created_year: int | None = None
        if user.created_at is not None:
            created_year = bound_calendar_date(user.created_at).year

        try:
            result = migration_estimate_dob(
                stored_age=int(age),
                created_at_year=created_year,
                fallback_business_year=fallback_year,
            )
        except AgePolicyValidationError:
            counts["unknown_invalid_age"] += 1
            continue

        counts["eligible_backfills"] += 1
        if dry_run:
            continue

        user.date_of_birth = result.date_of_birth
        user.dob_provenance = result.provenance
        user.dob_estimate_reference_year = result.reference_year
        db.add(user)
        counts["applied_backfills"] += 1

        if counts["applied_backfills"] % batch_size == 0:
            await db.flush()

    if not dry_run and counts["applied_backfills"] % batch_size != 0:
        await db.flush()

    provenance_rows = list(
        (
            await db.execute(
                select(User)
                .where(User.date_of_birth.isnot(None))
                .where(User.dob_provenance.is_(None))
                .order_by(User.user_id.asc())
            )
        ).scalars().all()
    )
    counts["labeled_unknown_provenance"] = 0
    for user in provenance_rows:
        counts["preserved_existing_dob"] += 1
        if dry_run:
            counts["labeled_unknown_provenance"] += 1
            continue
        user.dob_provenance = "unknown"
        db.add(user)
        counts["labeled_unknown_provenance"] += 1

    if not dry_run and counts["labeled_unknown_provenance"]:
        await db.flush()

    counts["dry_run"] = dry_run
    counts["fallback_business_year"] = fallback_year
    return counts