"""Regenerate Bio AI PDFs at existing slugs for one engagement.

Overwrites PDFs via POST /api/reports/regenerate without re-pushing Metsights data.
All external calls are logged to integration_sync_logs.

Entrypoint:

  python -m db.jobs.regenerate_engagement_bio_ai_pdfs --engagement-id <ID> --dry-run
  python -m db.jobs.regenerate_engagement_bio_ai_pdfs --engagement-id <ID> --yes
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from core.config import settings
from db.engine import create_job_engine, job_session_factory
from modules.bioai_report.regenerate_engagement_bio_ai_pdfs import (
    regenerate_engagement_bio_ai_pdfs,
)

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
    engagement_id: int,
) -> dict:
    settings.validate()

    if not yes and not dry_run:
        raise SystemExit(
            "Refusing to run without explicit confirmation. Re-run with --yes to apply changes, "
            "or --dry-run to preview."
        )

    engine = create_job_engine()
    session_factory = job_session_factory(engine)
    on_progress = _make_progress_printer()

    print(
        f"Regenerating Bio AI PDFs for engagement_id={engagement_id} "
        f"({'dry-run' if dry_run else 'apply'})...",
        flush=True,
    )

    async with session_factory() as session:
        result = await regenerate_engagement_bio_ai_pdfs(
            session,
            engagement_id=engagement_id,
            dry_run=dry_run,
            on_progress=on_progress,
        )

    await engine.dispose()
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate Bio AI PDFs at existing slugs for participants on one "
            "engagement. Does not re-push Metsights data or refresh report JSON."
        )
    )
    parser.add_argument(
        "--engagement-id",
        type=int,
        required=True,
        metavar="ID",
        help="Engagement to regenerate Bio AI PDFs for.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Apply changes. Without this flag (and without --dry-run), the command exits without writing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report matched participants without calling bio-ai-reports.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = asyncio.run(
        run_regenerate(
            yes=args.yes,
            dry_run=args.dry_run,
            engagement_id=args.engagement_id,
        )
    )
    mode = "dry-run" if result["dry_run"] else "applied"
    print(
        f"\nRegenerate engagement Bio AI PDFs ({mode}):\n"
        f"  engagement_id={result['engagement_id']}\n"
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
