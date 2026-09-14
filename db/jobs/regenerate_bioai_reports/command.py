"""Regenerate BioAI PDFs for eligible female booked participants.

Refreshes MetSights report JSON and overwrites PDFs at existing permanent slugs
via POST /api/reports/regenerate for participants in running engagements.

Entrypoint: ``python -m db.jobs.regenerate_bioai_reports --yes``

Suggested cron (install manually on server):
  0 3 * * * cd /var/www/backend/api && .venv/bin/python -m db.jobs.regenerate_bioai_reports --yes >> /var/log/regenerate_bioai_reports.log 2>&1
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date

from db.engine import create_job_engine, job_session_factory
from modules.metsights.client import MetsightsClient
from modules.metsights.service import MetsightsService
from modules.notifications.regenerate_bioai_reports import regenerate_bioai_reports

_PROGRESS_BAR_WIDTH = 30


def _format_progress(
    done: int,
    total: int,
    regenerated: int,
    skipped: int,
    failed: int,
) -> str:
    pct = 100 if total == 0 else int(100 * done / total)
    filled = _PROGRESS_BAR_WIDTH if total == 0 else int(_PROGRESS_BAR_WIDTH * done / total)
    bar = "█" * filled + "░" * (_PROGRESS_BAR_WIDTH - filled)
    return (
        f"[{bar}] {done}/{total} ({pct}%)  "
        f"regenerated={regenerated} skipped={skipped} failed={failed}"
    )


def _make_progress_printer():
    """Return a progress callback that redraws in-place on a TTY, or logs lines otherwise."""
    is_tty = sys.stdout.isatty()
    last_pct = -1

    def on_progress(
        done: int,
        total: int,
        regenerated: int,
        skipped: int,
        failed: int,
    ) -> None:
        nonlocal last_pct
        line = _format_progress(done, total, regenerated, skipped, failed)
        if is_tty:
            print(f"\r{line}", end="", flush=True)
            if done >= total:
                print(flush=True)
            return

        pct = 100 if total == 0 else int(100 * done / total)
        if done == 0 or done >= total or pct != last_pct:
            print(line, flush=True)
            last_pct = pct

    return on_progress


async def run_regenerate(
    *,
    yes: bool,
    dry_run: bool,
    as_of: date | None,
    engagement_id: int | None,
) -> dict:
    from core.config import settings

    settings.validate()

    if not yes and not dry_run:
        raise SystemExit(
            "Refusing to run without explicit confirmation. Re-run with --yes to apply changes, "
            "or --dry-run to preview."
        )

    engine = create_job_engine()
    session_factory = job_session_factory(engine)
    metsights_service = MetsightsService(client=MetsightsClient())
    on_progress = _make_progress_printer()

    if engagement_id is not None:
        print(
            f"Finding eligible female booked participants for engagement_id={engagement_id}...",
            flush=True,
        )
    else:
        print("Finding eligible female booked participants in running engagements...", flush=True)

    async with session_factory() as session:
        result = await regenerate_bioai_reports(
            session,
            metsights_service=metsights_service,
            as_of=as_of,
            dry_run=dry_run,
            engagement_id=engagement_id,
            on_progress=on_progress,
        )
        if not dry_run:
            await session.commit()

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
            "Regenerate BioAI PDFs at existing slugs for female booked participants "
            "in running engagements."
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
        help="Report matched participants without calling MetSights or bio-ai-reports.",
    )
    parser.add_argument(
        "--as-of",
        type=_parse_as_of,
        default=None,
        metavar="YYYY-MM-DD",
        help="Override 'today' date for engagement_date filtering.",
    )
    parser.add_argument(
        "--engagement-id",
        type=int,
        default=None,
        metavar="ID",
        help="Optional: limit to one engagement_id.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = asyncio.run(
        run_regenerate(
            yes=args.yes,
            dry_run=args.dry_run,
            as_of=args.as_of,
            engagement_id=args.engagement_id,
        )
    )
    mode = "dry-run" if result["dry_run"] else "applied"
    engagement_line = ""
    if result.get("engagement_id") is not None:
        engagement_line = f"  engagement_id={result['engagement_id']}\n"
    print(
        f"\nRegenerate BioAI reports ({mode}):\n"
        f"  as_of={result['as_of']}\n"
        f"{engagement_line}"
        f"  matched={result['matched']}, regenerated={result['regenerated']}, "
        f"skipped={result['skipped']}, failed={result['failed']}"
    )
    details = result.get("details", [])
    if details:
        print(f"\n  {'USER':>8}  {'ENG':>6}  {'ACTION':>12}  REASON")
        print(f"  {'─' * 8}  {'─' * 6}  {'─' * 12}  {'─' * 40}")
        for detail in details:
            print(
                f"  {detail['user_id']:>8}  {detail['engagement_id']:>6}  "
                f"{detail['action']:>12}  {detail['reason']}"
            )
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
