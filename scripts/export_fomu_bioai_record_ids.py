"""Export Force One November primary Bio AI Metsights record ids to CSV.

Run on production (reads DATABASE_URL from dev-api/.env or environment):

    cd /var/www/supershyft-api
    python scripts/export_fomu_bioai_record_ids.py --engagement-id 1253

Optional:

    --fallback-only     Only rows with fallback thyroid push (1.1 / 8.0 / 2.0) in sync logs
    --record-ids-only   Also write a one-column CSV for the Metsights team
    --output PATH       Default: docs/exports/fomu_bioai_primary_record_ids.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
from pathlib import Path

DEFAULT_ENGAGEMENT_ID = 1253
DEFAULT_CODE = "FOMU1026"


def load_dsn() -> str:
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        candidates = [
            Path.cwd() / ".env",
            Path(__file__).resolve().parents[1] / ".env",
        ]
        env_path = next((p for p in candidates if p.exists()), None)
        if env_path is not None:
            for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip().lstrip("\ufeff")
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == "DATABASE_URL":
                    raw = v.strip().strip('"').strip("'")
                    break
    if not raw:
        raise SystemExit("Set DATABASE_URL or run from directory with .env")
    return raw.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


def build_sql(*, fallback_only: bool) -> str:
    fallback_filter = ""
    if fallback_only:
        fallback_filter = " AND fp.user_id IS NOT NULL"

    return f"""
    WITH primary_instances AS (
        SELECT
            ep.user_id,
            ep.engagement_participant_id,
            ai.assessment_instance_id,
            TRIM(ai.metsights_record_id) AS metsights_record_id,
            ap.package_code,
            ap.assessment_type_code,
            ihr.report_id,
            ihr.report_url,
            (ihr.reports IS NOT NULL AND ihr.reports::text NOT IN ('null', '{{}}', '[]')) AS has_reports_json
        FROM engagement_participants ep
        JOIN engagements e ON e.engagement_id = ep.engagement_id
        JOIN assessment_instances ai
            ON ai.engagement_id = ep.engagement_id
           AND ai.user_id = ep.user_id
           AND ai.package_id = e.assessment_package_id
        JOIN assessment_packages ap ON ap.package_id = ai.package_id
        LEFT JOIN individual_health_report ihr
            ON ihr.assessment_instance_id = ai.assessment_instance_id
        WHERE ep.engagement_id = $1
          AND TRIM(COALESCE(ai.metsights_record_id, '')) <> ''
    ),
    fallback_push AS (
        SELECT DISTINCT isl.user_id
        FROM integration_sync_logs isl
        WHERE isl.engagement_id = $1
          AND isl.provider = 'metsights'
          AND isl.api_endpoint_url ILIKE '%blood-parameters%'
          AND (isl.request_payload->>'triiodothyronine') = '1.1'
          AND (isl.request_payload->>'thyroxine') = '8.0'
          AND (isl.request_payload->>'tsh_value') = '2.0'
    )
    SELECT
        pi.user_id,
        pi.assessment_instance_id,
        pi.metsights_record_id,
        pi.package_code,
        pi.assessment_type_code,
        pi.report_url,
        pi.has_reports_json,
        (fp.user_id IS NOT NULL) AS had_fallback_thyroid_push
    FROM primary_instances pi
    LEFT JOIN fallback_push fp ON fp.user_id = pi.user_id
    WHERE pi.report_url IS NOT NULL
      AND TRIM(pi.report_url) <> ''
      AND pi.has_reports_json
      {fallback_filter}
    ORDER BY pi.metsights_record_id, pi.user_id;
    """


async def run(
    *,
    engagement_id: int,
    engagement_code: str,
    output: Path,
    record_ids_only: Path | None,
    fallback_only: bool,
) -> dict:
    import asyncpg

    conn = await asyncpg.connect(load_dsn())
    try:
        await conn.execute("SET default_transaction_read_only = on")
        rows = await conn.fetch(build_sql(fallback_only=fallback_only), engagement_id)
    finally:
        await conn.close()

    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "engagement_id",
        "engagement_code",
        "user_id",
        "assessment_instance_id",
        "metsights_record_id",
        "package_code",
        "assessment_type_code",
        "had_fallback_thyroid_push",
        "report_url",
    ]
    with output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "engagement_id": engagement_id,
                    "engagement_code": engagement_code,
                    "user_id": r["user_id"],
                    "assessment_instance_id": r["assessment_instance_id"],
                    "metsights_record_id": r["metsights_record_id"],
                    "package_code": r["package_code"],
                    "assessment_type_code": r["assessment_type_code"],
                    "had_fallback_thyroid_push": r["had_fallback_thyroid_push"],
                    "report_url": r["report_url"] or "",
                }
            )

    if record_ids_only is not None:
        record_ids_only.parent.mkdir(parents=True, exist_ok=True)
        seen: set[str] = set()
        with record_ids_only.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["metsights_record_id"])
            for r in rows:
                rid = (r["metsights_record_id"] or "").strip()
                if rid and rid not in seen:
                    seen.add(rid)
                    w.writerow([rid])

    return {
        "engagement_id": engagement_id,
        "rows": len(rows),
        "unique_record_ids": len({(r["metsights_record_id"] or "").strip() for r in rows}),
        "fallback_only": fallback_only,
        "output": str(output),
        "record_ids_only": str(record_ids_only) if record_ids_only else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engagement-id", type=int, default=DEFAULT_ENGAGEMENT_ID)
    parser.add_argument("--engagement-code", type=str, default=DEFAULT_CODE)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "docs"
        / "exports"
        / "fomu_bioai_primary_record_ids.csv",
    )
    parser.add_argument(
        "--record-ids-only",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "docs"
        / "exports"
        / "fomu_bioai_metsights_record_ids_only.csv",
    )
    parser.add_argument(
        "--no-record-ids-only",
        action="store_true",
        help="Skip the one-column Metsights handoff file",
    )
    parser.add_argument(
        "--fallback-only",
        action="store_true",
        help="Only participants whose blood-parameters push used fallback thyroid values",
    )
    args = parser.parse_args(argv)

    record_ids_path = None if args.no_record_ids_only else args.record_ids_only
    summary = asyncio.run(
        run(
            engagement_id=args.engagement_id,
            engagement_code=args.engagement_code,
            output=args.output,
            record_ids_only=record_ids_path,
            fallback_only=args.fallback_only,
        )
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())