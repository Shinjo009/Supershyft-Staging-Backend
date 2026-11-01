#!/usr/bin/env python3
"""Scan n8n workflows and emit notification_services content artifact + report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.notifications.n8n_workflow_parser import (  # noqa: E402
    build_content_artifact,
    parse_workflow_file,
    parse_workflows_dir,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate n8n workflow content to JSON artifact")
    parser.add_argument(
        "--workflows-dir",
        type=Path,
        default=ROOT / "n8n" / "workflows",
        help="Directory containing n8n workflow JSON files",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "db" / "migrations" / "data" / "0187_notification_content.json",
        help="Output artifact path for Alembic 0187",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "reports" / "n8n_migration_report.json",
        help="Human-readable migration report",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not write files")
    args = parser.parse_args()

    report = parse_workflows_dir(args.workflows_dir)
    artifact = build_content_artifact(args.workflows_dir)

    report_payload = {
        "service_count": len(artifact),
        "unmatched_webhook_paths": report.unmatched_webhook_paths,
        "warnings": report.warnings,
        "services": [
            {
                "service_key": s.service_key,
                "webhook_path": s.webhook_path,
                "workflow_file": s.workflow_file,
                "channel": s.channel,
                "template_name": s.template_name,
                "param_count": len(
                    (s.template_variables or [{}])[0].get("parameters", [])
                    if s.template_variables
                    else []
                ),
                "warnings": s.warnings,
            }
            for s in report.services
        ],
    }

    if args.dry_run:
        print(json.dumps({"artifact_rows": len(artifact), "report": report_payload}, indent=2))
        return

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.report.write_text(json.dumps(report_payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(artifact)} service rows to {args.out}")
    print(f"Report: {args.report}")


if __name__ == "__main__":
    main()
