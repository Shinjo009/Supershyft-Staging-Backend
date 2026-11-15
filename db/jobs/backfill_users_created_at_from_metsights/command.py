"""Backfill users.created_at from Metsights profile detail.

Entrypoint: ``python -m db.jobs.backfill_users_created_at_from_metsights --dry-run``
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker

from core.config import settings
from db.engine import create_job_engine, job_session_factory
from modules.metsights.client import MetsightsClient
from modules.metsights.service import MetsightsService
from modules.users.backfill_created_at_from_metsights import backfill_users_created_at_from_metsights
from modules.users.repository import UsersRepository

_PROGRESS_BAR_WIDTH = 30
_NON_TTY_PRINT_EVERY = 5
_PROGRESS_LINE_PAD = 120


def _format_progress(
    done: int,
    total: int,
    updated: int,
    skipped: int,
    failed: int,
) -> str:
    pct = 100 if total == 0 else int(100 * done / total)
    filled = _PROGRESS_BAR_WIDTH if total == 0 else int(_PROGRESS_BAR_WIDTH * done / total)
    bar = "█" * filled + "░" * (_PROGRESS_BAR_WIDTH - filled)
    return (
        f"[{bar}] {done}/{total} ({pct}%)  "
        f"updated={updated} skipped={skipped} failed={failed}"
    )


def _make_progress_printer():
    is_tty = sys.stdout.isatty()
    last_counts: tuple[int, int, int] | None = None
    last_printed_done = -1

    def on_progress(
        done: int,
        total: int,
        updated: int,
        skipped: int,
        failed: int,
    ) -> None:
        nonlocal last_counts, last_printed_done
        line = _format_progress(done, total, updated, skipped, failed)
        counts = (updated, skipped, failed)

        if is_tty:
            padded = line.ljust(_PROGRESS_LINE_PAD)
            print(f"\r{padded}", end="", flush=True)
            if done >= total:
                print(flush=True)
            return

        counts_changed = counts != last_counts
        should_print = (
            done == 0
            or done >= total
            or counts_changed
            or (done - last_printed_done) >= _NON_TTY_PRINT_EVERY
        )
        if should_print:
            print(line, flush=True)
            last_counts = counts
            last_printed_done = done

    return on_progress


async def run_backfill(
    *,
    yes: bool,
    dry_run: bool,
    user_id: int | None,
    limit: int | None,
    sleep_ms: int,
    batch_size: int,
) -> dict:
    settings.validate()

    if not yes and not dry_run:
        raise SystemExit(
            "Refusing to run without explicit confirmation. Re-run with --yes to apply changes, "
            "or --dry-run to preview."
        )

    engine = create_job_engine()
    session_factory: async_sessionmaker = job_session_factory(engine)

    metsights_client = MetsightsClient()
    metsights_service = MetsightsService(client=metsights_client)
    on_progress = _make_progress_printer()
    print(
        f"Loading users with NULL created_at and Metsights profile id "
        f"({'dry-run' if dry_run else 'apply'})...",
        flush=True,
    )

    async with session_factory() as session:
        result = await backfill_users_created_at_from_metsights(
            session,
            metsights_service=metsights_service,
            users_repo=UsersRepository(),
            user_id=user_id,
            limit=limit,
            dry_run=dry_run,
            sleep_ms=sleep_ms,
            batch_size=batch_size,
            on_progress=on_progress,
        )

    await engine.dispose()
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill users.created_at from MetSights GET /external/profiles/:id/."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Apply changes. Without this flag (and without --dry-run), the command exits without writing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be updated without making changes.",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="Process a single user id (must have NULL created_at and Metsights profile id).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max users to process.",
    )
    parser.add_argument(
        "--sleep-ms",
        type=int,
        default=50,
        help="Delay between MetSights API calls in milliseconds (default: 50).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Commit after this many successful updates (default: 25).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = asyncio.run(
        run_backfill(
            yes=args.yes,
            dry_run=args.dry_run,
            user_id=args.user_id,
            limit=args.limit,
            sleep_ms=args.sleep_ms,
            batch_size=args.batch_size,
        )
    )
    mode = "dry-run" if result.get("dry_run") else "applied"
    print(
        f"\nBackfill users.created_at ({mode}): "
        f"matched={result.get('matched')} updated={result.get('updated')} "
        f"skipped={result.get('skipped')} failed={result.get('failed')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())