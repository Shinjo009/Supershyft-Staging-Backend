"""Remediate BioAI batch generated without archived diagnostic blood PDF.

Entrypoint: ``python -m db.jobs.remediate_bad_bioai_batch --engagement-id 1123 --dry-run``
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from core.config import settings
from db.engine import create_job_engine, job_session_factory
from modules.assessments.dependencies import get_assessments_service
from modules.engagements.dependencies import get_engagements_service
from modules.maintenance.remediate_bad_bioai_batch import remediate_bad_bioai_batch
from modules.metsights.client import MetsightsClient
from modules.metsights.service import MetsightsService
from modules.metsights.sync_service import MetsightsSyncService
from modules.platform_settings.dependencies import get_platform_settings_service_readonly
from modules.questionnaire.repository import QuestionnaireRepository
from modules.users.repository import UsersRepository

logger = logging.getLogger(__name__)

_PROGRESS_BAR_WIDTH = 30


def _parse_user_ids(raw: str | None) -> set[int] | None:
    if raw is None or not raw.strip():
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return {int(p) for p in parts}


def _format_progress(
    done: int,
    total: int,
    remediated: int,
    skipped: int,
    failed: int,
) -> str:
    pct = 100 if total == 0 else int(100 * done / total)
    filled = _PROGRESS_BAR_WIDTH if total == 0 else int(_PROGRESS_BAR_WIDTH * done / total)
    bar = "█" * filled + "░" * (_PROGRESS_BAR_WIDTH - filled)
    return (
        f"[{bar}] {done}/{total} ({pct}%)  "
        f"remediated={remediated} skipped={skipped} failed={failed}"
    )


def _make_progress_printer():
    is_tty = sys.stdout.isatty()
    last_pct = -1

    def on_progress(
        done: int,
        total: int,
        remediated: int,
        skipped: int,
        failed: int,
    ) -> None:
        nonlocal last_pct
        line = _format_progress(done, total, remediated, skipped, failed)
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


async def run_remediate(
    *,
    yes: bool,
    dry_run: bool,
    engagement_id: int,
    user_ids: set[int] | None,
    include_with_archived_blood: bool,
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
    metsights_service = MetsightsService(client=MetsightsClient())
    sync_service = MetsightsSyncService(
        metsights_service=metsights_service,
        users_repository=UsersRepository(),
        engagements_service=get_engagements_service(),
        assessments_service=get_assessments_service(),
        platform_settings_service=get_platform_settings_service_readonly(),
        questionnaire_repository=QuestionnaireRepository(),
    )
    on_progress = _make_progress_printer()

    print(
        f"Remediating bad BioAI batch for engagement_id={engagement_id} "
        f"(dry_run={dry_run})...",
        flush=True,
    )

    async with session_factory() as session:
        result = await remediate_bad_bioai_batch(
            session,
            engagement_id=engagement_id,
            metsights_service=metsights_service,
            sync_service=sync_service,
            dry_run=dry_run,
            user_ids=user_ids,
            include_with_archived_blood=include_with_archived_blood,
            on_progress=on_progress,
        )

    await engine.dispose()

    if report_path:
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        logger.info("Wrote report to %s", path)

    print(
        f"Done: matched={result.get('matched')} remediated={result.get('remediated')} "
        f"skipped={result.get('skipped')} failed={result.get('failed')}",
        flush=True,
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Remediate bad BioAI batch for one engagement.")
    parser.add_argument("--yes", action="store_true", help="Apply changes.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without applying.")
    parser.add_argument("--engagement-id", type=int, required=True)
    parser.add_argument("--user-ids", type=str, default=None, help="Comma-separated user ids.")
    parser.add_argument(
        "--include-with-archived-blood",
        action="store_true",
        help="Include participants who already have an archived diagnostic blood PDF.",
    )
    parser.add_argument("--report", type=str, default=None, help="Write JSON summary to this path.")
    args = parser.parse_args()

    asyncio.run(
        run_remediate(
            yes=args.yes,
            dry_run=args.dry_run,
            engagement_id=args.engagement_id,
            user_ids=_parse_user_ids(args.user_ids),
            include_with_archived_blood=args.include_with_archived_blood,
            report_path=args.report,
        )
    )


if __name__ == "__main__":
    main()
