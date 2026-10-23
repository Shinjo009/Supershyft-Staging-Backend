"""Generate notification service content fixtures from n8n workflows (git commit e543900)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from modules.notifications.n8n_workflow_parser import (
    find_chained_dispatches,
    parse_prepare_node,
    parse_workflow,
    webhook_path_from_workflow,
)

GIT_REF = "e543900"
REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_SERVICES = REPO_ROOT / "db" / "fixtures" / "notification_services_content.json"
OUT_MANIFEST = REPO_ROOT / "db" / "fixtures" / "n8n_workflow_service_map.json"
STAGING_SNAPSHOT = REPO_ROOT / "db" / "fixtures" / "notification_snapshot_staging.json"
OVERRIDES_PATH = REPO_ROOT / "db" / "fixtures" / "notification_services_overrides.json"
TEMPLATES_SIMPLE = REPO_ROOT.parents[0] / "templates-json-simple.json"
if not TEMPLATES_SIMPLE.is_file():
    TEMPLATES_SIMPLE = REPO_ROOT / "templates-json-simple.json"


def _git_list_workflows() -> list[str]:
    out = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", GIT_REF, "n8n/workflows"],
        cwd=REPO_ROOT,
        text=True,
    )
    return [line.strip() for line in out.splitlines() if line.endswith(".json")]


def _git_read_workflow(path: str) -> dict:
    raw = subprocess.check_output(["git", "show", f"{GIT_REF}:{path}"], cwd=REPO_ROOT)
    return json.loads(raw)


def _norm_key(value: str) -> str:
    value = value.strip().lstrip("/")
    value = value.replace("+", "-").replace("1+1", "1plus1").replace("1-1", "1plus1")
    value = re.sub(r"-v\d+([+-].*)?$", "", value)
    value = re.sub(r"-v\d+$", "", value)
    return value


def _service_key_from_webhook(webhook_path: str, known_keys: set[str], aliases: dict[str, str]) -> str | None:
    wp = webhook_path.strip().lstrip("/")
    if wp in aliases:
        return aliases[wp]
    if wp in known_keys:
        return wp
    nwp = _norm_key(wp)
    for key in known_keys:
        if _norm_key(key) == nwp:
            return key
    base = re.sub(r"-v\d+([+-].*)?$", "", wp)
    base = re.sub(r"-v\d+$", "", base)
    for key in known_keys:
        if key.startswith(base) or base.startswith(key):
            return key
    return None


def _load_waba_body_param_counts() -> dict[str, int]:
    if not TEMPLATES_SIMPLE.is_file():
        return {}
    data = json.loads(TEMPLATES_SIMPLE.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    for entry in data:
        name = entry.get("name")
        if not name:
            continue
        components = (entry.get("template") or {}).get("components") or []
        for comp in components:
            if comp.get("type") == "body":
                counts[str(name)] = len(comp.get("parameters") or [])
    return counts


def _apply_parsed_to_row(row: dict[str, Any], parsed_content: Any, *, force: bool = False) -> bool:
    changed = False
    ch = row.get("channel")
    if parsed_content.channel == "whatsapp" or ch == "whatsapp":
        if parsed_content.template_name and (force or not (row.get("template_name") or "").strip()):
            row["template_name"] = parsed_content.template_name
            changed = True
        if parsed_content.template_variables and (force or not row.get("template_variables")):
            row["template_variables"] = parsed_content.template_variables
            changed = True
    if parsed_content.email_subject or parsed_content.email_body or parsed_content.email_html:
        if parsed_content.email_subject and (force or not (row.get("email_subject") or "").strip()):
            row["email_subject"] = parsed_content.email_subject
            changed = True
        if parsed_content.email_html and (force or not (row.get("email_html") or "").strip()):
            row["email_html"] = parsed_content.email_html
            changed = True
        if parsed_content.email_body and (force or not (row.get("email_body") or "").strip()):
            row["email_body"] = parsed_content.email_body
            changed = True
    return changed


def _row_from_split(base: dict[str, Any], split: dict[str, Any], parsed: Any) -> dict[str, Any]:
    row = {
        "service_key": split["service_key"],
        "display_name": split.get("display_name") or split["service_key"],
        "channel": split["channel"],
        "is_active": True,
        "template_name": None,
        "template_variables": None,
        "email_subject": None,
        "email_body": None,
        "email_html": None,
    }
    if parsed:
        _apply_parsed_to_row(row, parsed, force=True)
    return row


def main() -> int:
    if not STAGING_SNAPSHOT.is_file():
        print("Missing staging snapshot", file=sys.stderr)
        return 1

    overrides: dict[str, Any] = {}
    if OVERRIDES_PATH.is_file():
        overrides = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))

    aliases = overrides.get("webhook_to_service_key") or {}
    staging = json.loads(STAGING_SNAPSHOT.read_text(encoding="utf-8"))
    services_by_key: dict[str, dict[str, Any]] = {s["service_key"]: dict(s) for s in staging["services"]}
    known_keys = set(services_by_key)

    waba_counts = _load_waba_body_param_counts()
    manifest_entries: list[dict[str, Any]] = []
    warnings: list[str] = []

    for wf_path in _git_list_workflows():
        wf = _git_read_workflow(wf_path)
        wp = webhook_path_from_workflow(wf)
        sk = _service_key_from_webhook(wp or "", known_keys, aliases) if wp else None
        parsed = parse_workflow(wf, workflow_file=wf_path)
        chains = find_chained_dispatches(wf)

        entry: dict[str, Any] = {
            "workflow_file": wf_path,
            "webhook_path": wp,
            "primary_service_key": sk,
            "template_name": parsed.primary.template_name if parsed.primary else None,
            "template_variables": parsed.primary.template_variables if parsed.primary else None,
            "chained_dispatches": [
                {k: v for k, v in c.items() if k in ("service_key", "node_name")}
                for c in chains
            ],
        }
        manifest_entries.append(entry)

        if sk and sk in services_by_key and parsed.primary:
            _apply_parsed_to_row(services_by_key[sk], parsed.primary, force=True)
        if sk and sk in services_by_key and parsed.email:
            _apply_parsed_to_row(services_by_key[sk], parsed.email, force=True)

        if sk and parsed.primary and parsed.primary.template_name:
            tn = parsed.primary.template_name
            tv = parsed.primary.template_variables or []
            expected = waba_counts.get(tn)
            if expected is not None and len(tv) != expected:
                warnings.append(
                    f"{sk}: template {tn} has {len(tv)} vars, WABA expects {expected}"
                )

        split_rules = (overrides.get("split_services") or {}).get(sk) or []
        for split in split_rules:
            node_parsed = parse_prepare_node(wf, name_contains=split["prepare_node_name_contains"])
            new_row = _row_from_split(services_by_key.get(sk, {}), split, node_parsed)
            services_by_key[split["service_key"]] = new_row
            known_keys.add(split["service_key"])

    for sk in overrides.get("deprecated_service_keys") or []:
        if sk in services_by_key:
            services_by_key[sk]["is_active"] = False

    for sk, patch in (overrides.get("service_content") or {}).items():
        if sk not in services_by_key:
            continue
        row = services_by_key[sk]
        for key, val in patch.items():
            row[key] = val

    for sk, row in services_by_key.items():
        if not row.get("is_active", True):
            continue
        ch = row.get("channel")
        if ch == "whatsapp" and not (row.get("template_name") or "").strip():
            warnings.append(f"{sk}: active whatsapp service missing template_name")
        if ch == "email" and not (row.get("email_subject") or "").strip():
            row.setdefault("email_subject", row.get("display_name") or sk)
            row.setdefault(
                "email_body",
                "Hello {{first_name}},\n\nThis is a notification from SuperShyft.",
            )
            row.setdefault(
                "email_html",
                "<p>Hello {{first_name}},</p><p>This is a notification from SuperShyft.</p>",
            )

    out_list = [services_by_key[k] for k in sorted(services_by_key)]
    OUT_SERVICES.parent.mkdir(parents=True, exist_ok=True)
    OUT_SERVICES.write_text(json.dumps(out_list, indent=2), encoding="utf-8")
    OUT_MANIFEST.write_text(json.dumps(manifest_entries, indent=2), encoding="utf-8")

    filled = sum(
        1
        for s in out_list
        if (s.get("template_name") or "").strip() or (s.get("email_subject") or "").strip()
    )
    print(f"Wrote {OUT_SERVICES}: {len(out_list)} services, {filled} with content")
    print(f"Wrote {OUT_MANIFEST}: {len(manifest_entries)} workflows")
    if warnings:
        print(f"{len(warnings)} validation warnings:", file=sys.stderr)
        for w in warnings[:40]:
            print(f"  - {w}", file=sys.stderr)
        if len(warnings) > 40:
            print(f"  ... and {len(warnings) - 40} more", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
