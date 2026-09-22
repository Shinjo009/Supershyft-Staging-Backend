"""Backfill report notifications as sent for CBTW + Celebal (DB-only, embedded data).

No Excel file is required at runtime. Data is embedded in
``modules.notifications.report_sent_backfill_data``.

Cohorts:
  engagement_id 16 — CBTW Pvt ltd
  engagement_id 72 — Celebal Technologies Male
  engagement_id 73 — Celebal Technologies Female

::

    python -m db.jobs.backfill_report_sent --dry-run
    python -m db.jobs.backfill_report_sent --yes
    python -m db.jobs.backfill_report_sent --yes --engagement-id 72 --engagement-id 73
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from core.config import settings
from db.engine import create_job_engine, job_session_factory
from modules.notifications.backfill_report_sent import backfill_report_sent

logger = logging.getLogger(__name__)


async def run_backfill(
    *,
    yes: bool,
    dry_run: bool,
    engagement_ids: list[int] | None,
    report_path: str | None,
) -> dict:
    settings.validate()

    if not yes and not dry_run:
        raise SystemExit(
            "Refusing to run without explicit confirmation. Re-run with --yes to apply changes, "
            "or --dry-run to preview."
        )

    engine = create_job_engine()
    session_factory = job_session_factory(engine)

    async with session_factory() as session:
        result = await backfill_report_sent(
            session,
            engagement_ids=engagement_ids,
            dry_run=dry_run,
        )
        if not dry_run:
            await session.commit()

    await engine.dispose()

    payload = result.to_dict()
    if report_path:
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        logger.info("Wrote report to %s", path)

    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Ensure users exist and are enrolled, then INSERT/UPDATE "
            "notifications.status=sent only for Excel-ticked report channels "
            "on engagements 16/72/73 (blank cells ignored). "
            "Uses embedded registration data (no Excel). Never sends notifications."
        )
    )
    parser.add_argument("--yes", action="store_true", help="Apply DB changes.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing.")
    parser.add_argument(
        "--engagement-id",
        type=int,
        action="append",
        dest="engagement_ids",
        default=None,
        help="Limit to one or more engagement ids (repeatable). Default: 16, 72, 73.",
    )
    parser.add_argument(
        "--report",
        type=str,
        default=None,
        help="Write JSON report to this path.",
    )
    return parser


def _print_summary(result: dict) -> None:
    mode = "dry-run" if result.get("dry_run") else "applied"
    print(f"\nReport-sent backfill ({mode}):")
    print(f"  source={result.get('source')}")
    totals = result.get("totals") or {}
    print(f"  totals.rows_read={totals.get('rows_read')}")
    print(f"  totals.users_found={totals.get('users_found')}")
    print(f"  totals.users_created={totals.get('users_created')}")
    print(f"  totals.enrollments_created={totals.get('enrollments_created')}")
    print(f"  totals.notifications_inserted={totals.get('notifications_inserted')}")
    print(f"  totals.notifications_updated={totals.get('notifications_updated')}")
    print(f"  totals.notifications_skipped={totals.get('notifications_skipped')}")
    print(f"  totals.errors={totals.get('errors')}")
    for cohort in result.get("cohorts") or []:
        print(
            f"  - engagement_id={cohort.get('engagement_id')} "
            f"({cohort.get('label')}): "
            f"rows={cohort.get('rows_read')} "
            f"found={cohort.get('users_found')} "
            f"created={cohort.get('users_created')} "
            f"enroll={cohort.get('enrollments_created')} "
            f"ins={cohort.get('notifications_inserted')} "
            f"upd={cohort.get('notifications_updated')} "
            f"skip={cohort.get('notifications_skipped')} "
            f"errors={len(cohort.get('errors') or [])}"
        )
        for err in (cohort.get("errors") or [])[:10]:
            print(f"      error: {err}")
    print()


def main(argv: list[str] | None = None) -> int:
    load_dotenv(override=False)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    args = _build_parser().parse_args(argv)
    result = asyncio.run(
        run_backfill(
            yes=args.yes,
            dry_run=args.dry_run,
            engagement_ids=args.engagement_ids,
            report_path=args.report,
        )
    )
    _print_summary(result)
    totals = result.get("totals") or {}
    return 1 if totals.get("errors") else 0


if __name__ == "__main__":
    sys.exit(main())
