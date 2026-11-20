"""Dispatch consultation guide notifications for configured engagement recipients.

Finds scheduled or running engagements whose consultation slot_detail has an
enabled date tomorrow (IST) and dispatches ``reminders.consultation_guide``
notifications to each configured recipient type (e.g. expert assistants and
staff assistants). Recipients already sent successfully (or still in flight)
are skipped on re-run; failed recipients are retried.

Production example (Linux cron, IST):

    # 4:30pm IST — consultation-guide recipients for engagements with consultation tomorrow
    30 16 * * * cd /path/to/dev-api && TZ=Asia/Kolkata /path/to/venv/bin/python -m db.jobs.dispatch_consultation_guide_reminders --yes >> /var/log/supershyft/consultation-guide-reminders.log 2>&1

Entrypoint: ``python -m db.jobs.dispatch_consultation_guide_reminders --yes``
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date

from sqlalchemy.ext.asyncio import async_sessionmaker

from core.config import settings
from db.engine import create_job_engine, job_session_factory
from modules.engagements.repository import EngagementsRepository
from modules.notifications.consultation_guide_reminders import (
    dispatch_consultation_guide_reminders,
)
from modules.notifications.repository import NotificationsRepository
from modules.notifications.service import NotificationsService


async def run_dispatch_consultation_guide_reminders(
    *,
    yes: bool,
    dry_run: bool,
    as_of: date | None,
) -> dict:
    settings.validate()

    if not yes and not dry_run:
        raise SystemExit(
            "Refusing to run without explicit confirmation. Re-run with --yes to apply changes, "
            "or --dry-run to preview."
        )

    engine = create_job_engine()
    session_factory = job_session_factory(engine)

    notifications_service = NotificationsService(NotificationsRepository())
    engagements_repository = EngagementsRepository()

    async with session_factory() as session:
        async with session.begin():
            result = await dispatch_consultation_guide_reminders(
                session,
                notifications_service=notifications_service,
                engagements_repository=engagements_repository,
                as_of=as_of,
                dry_run=dry_run,
            )

    await engine.dispose()
    return result


def _parse_as_of(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}'. Expected YYYY-MM-DD.") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Dispatch consultation guide reminders for engagements with an enabled "
            "consultation date tomorrow (IST) in scheduled or running engagements, "
            "using each engagement's consultation_guide notification service keys."
        )
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Apply changes. Without this flag (and without --dry-run), the command exits without writing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many configured recipients would be notified without dispatching.",
    )
    parser.add_argument(
        "--as-of",
        type=_parse_as_of,
        default=None,
        metavar="YYYY-MM-DD",
        help="Reference date for tomorrow calculation (default: today in IST). Useful for testing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = asyncio.run(
        run_dispatch_consultation_guide_reminders(
            yes=args.yes,
            dry_run=args.dry_run,
            as_of=args.as_of,
        )
    )
    mode = "dry-run" if result["dry_run"] else "applied"
    print(
        f"Dispatch consultation guide reminders ({mode}): "
        f"as_of={result['as_of']}, consultation_date={result['consultation_date']}, "
        f"matched={result['matched']}, sent={result['sent']}, "
        f"skipped={result['skipped']}, failed={result['failed']}"
    )
    return 0