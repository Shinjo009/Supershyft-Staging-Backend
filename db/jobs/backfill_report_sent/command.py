"""Backfill report notifications as sent (DB-only, embedded data).

No Excel file is required at runtime. Data is embedded in
``modules.notifications.report_sent_backfill_data``.

Cohorts:
  engagement_id 16 — CBTW Pvt ltd
  engagement_id 72 — Celebal Technologies Male
  engagement_id 73 — Celebal Technologies Female

INSERT if missing; skip if a notification already exists (never UPDATE).

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
from typing import Any

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
            "Ensure users exist and are enrolled, then INSERT "
            "notifications.status=sent only for Excel-ticked report channels "
            "on engagements 16/72/73 when missing (skip if present; never UPDATE). "
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


def _format_name(action: dict[str, Any]) -> str:
    first = (action.get("first_name") or "").strip()
    last = (action.get("last_name") or "").strip()
    return f"{first} {last}".strip() or "-"


def _print_user_action(action: dict[str, Any]) -> None:
    name = _format_name(action)
    user_id = action.get("user_id")
    user_bit = f"user_id={user_id}" if user_id is not None else f"user={action.get('user', '-')}"
    print(
        f"      {user_bit} "
        f"name={name!r} "
        f"phone={action.get('phone')!r} "
        f"email={action.get('email')!r}"
    )
    if action.get("enroll") == "would_enroll":
        print("        enroll=would_enroll")
    elif action.get("enrolled") is True:
        print("        enroll=created")
    notifications = action.get("notifications")
    if notifications == "would_insert_after_create":
        channels = action.get("channels") or []
        print(f"        notifications=would_insert_after_create channels={channels}")
        return
    if isinstance(notifications, list):
        for ch in notifications:
            if ch.get("error"):
                print(f"        {ch.get('service_key')}: error={ch.get('error')}")
            else:
                extra = ""
                if ch.get("notification_id") is not None:
                    extra += f" notification_id={ch.get('notification_id')}"
                if ch.get("status") is not None:
                    extra += f" status={ch.get('status')!r}"
                print(f"        {ch.get('service_key')}: {ch.get('action')}{extra}")


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
        for action in cohort.get("actions") or []:
            _print_user_action(action)
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
