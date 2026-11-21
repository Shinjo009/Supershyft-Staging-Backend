"""Backfill users.date_of_birth from legacy age + created_at year.

Entrypoint: ``python -m db.jobs.backfill_user_dob_estimates --dry-run``
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date

from sqlalchemy.ext.asyncio import async_sessionmaker

from core.config import settings
from db.engine import create_job_engine, job_session_factory
from modules.users.backfill_user_dob_estimates import backfill_user_dob_estimates


async def run_backfill(
    *,
    yes: bool,
    dry_run: bool,
    user_id: int | None,
    batch_size: int,
    business_date: date | None,
) -> dict:
    settings.validate()

    if not yes and not dry_run:
        raise SystemExit(
            "Refusing to run without explicit confirmation. Re-run with --yes to apply changes, "
            "or --dry-run to preview."
        )

    engine = create_job_engine()
    session_factory: async_sessionmaker = job_session_factory(engine)

    async with session_factory() as session:
        result = await backfill_user_dob_estimates(
            session,
            dry_run=dry_run,
            batch_size=batch_size,
            user_id=user_id,
            fallback_business_date=business_date,
        )
        if not dry_run:
            await session.commit()

    await engine.dispose()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill estimated DOB for users missing date_of_birth.")
    parser.add_argument("--yes", action="store_true", help="Apply changes.")
    parser.add_argument("--dry-run", action="store_true", help="Preview counts only.")
    parser.add_argument("--user-id", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--business-date",
        type=str,
        default=None,
        help="IST fallback business date (YYYY-MM-DD) when created_at is null.",
    )
    args = parser.parse_args()

    business_date = date.fromisoformat(args.business_date) if args.business_date else None

    result = asyncio.run(
        run_backfill(
            yes=args.yes,
            dry_run=args.dry_run,
            user_id=args.user_id,
            batch_size=args.batch_size,
            business_date=business_date,
        )
    )
    print(result)


if __name__ == "__main__":
    main()