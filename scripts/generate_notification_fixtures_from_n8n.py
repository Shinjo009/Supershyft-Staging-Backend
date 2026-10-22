"""Generate notification service content fixtures from n8n workflows (git commit e543900)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

GIT_REF = "e543900"
WORKFLOW_PREFIX = "n8n/workflows/"
REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_SERVICES = REPO_ROOT / "db" / "fixtures" / "notification_services_content.json"
STAGING_SNAPSHOT = REPO_ROOT / "db" / "fixtures" / "notification_snapshot_staging.json"


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


def _webhook_path(workflow: dict) -> str | None:
    for node in workflow.get("nodes", []):
        if "webhook" in (node.get("type") or "").lower():
            path = (node.get("parameters") or {}).get("path")
            if path:
                return str(path).strip()
    return None


def _service_key_from_webhook(webhook_path: str, known_keys: set[str]) -> str | None:
    wp = webhook_path.strip().lstrip("/")
    if wp in known_keys:
        return wp
    # welcome-whatsapp-v3 -> welcome-whatsapp
    base = re.sub(r"-v\d+([+-].*)?$", "", wp)
    base = re.sub(r"-v\d+$", "", base)
    if base in known_keys:
        return base
    # booking-alert-whatsapp-1-1-v1 style
    for key in known_keys:
        if wp.startswith(key) or key.startswith(base):
            return key
    # filename style: path without version
    alt = wp.replace("-v1", "").replace("-v2", "").replace("-v3", "")
    if alt in known_keys:
        return alt
    return None


def _template_name_from_service_key(service_key: str) -> str:
    if service_key in ("whatapi-otp",):
        return "otp_new"
    if "otp" in service_key:
        return "otp_new"
    if service_key.startswith("welcome"):
        return "welcome_new"
    if service_key.startswith("pretest"):
        return "pretest_new"
    if "booking-confirmation" in service_key:
        return "booking_confirmation"
    if "consultation" in service_key and "remainder" in service_key:
        return "consultation_remainder"
    base = service_key
    for suffix in ("-whatsapp", "-email", "-session-v1", "-1plus1-v1", "-v1", "-v2", "-v3"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    base = re.sub(r"-\d+(\.\d+)?$", "", base)
    return base.replace("-", "_")[:64]


def _template_name_from_workflow(workflow: dict, service_key: str) -> str | None:
    _ = workflow
    return _template_name_from_service_key(service_key)


def _email_content_from_workflow(workflow: dict) -> tuple[str | None, str | None, str | None]:
    subject = body = html = None
    for node in workflow.get("nodes", []):
        if "emailSend" not in (node.get("type") or ""):
            continue
        p = node.get("parameters") or {}
        subject = str(p.get("subject") or subject or "")
        html = str(p.get("html") or p.get("htmlBody") or html or "")
        body = str(p.get("text") or p.get("message") or body or "")
    # strip n8n expressions for fixture defaults
    def clean(v: str | None) -> str | None:
        if not v:
            return None
        v = v.strip()
        if v.startswith("="):
            v = v[1:].strip()
        if "{{" in v and "}}" in v:
            return v  # keep as template with placeholders
        return v or None

    return clean(subject), clean(body), clean(html)


def _template_variables_from_requires(service: dict) -> list | None:
    tv = service.get("template_variables")
    if tv:
        return tv
    return None


def main() -> int:
    if not STAGING_SNAPSHOT.is_file():
        print("Missing staging snapshot; run export first", file=sys.stderr)
        return 1
    staging = json.loads(STAGING_SNAPSHOT.read_text(encoding="utf-8"))
    services_by_key = {s["service_key"]: dict(s) for s in staging["services"]}
    known_keys = set(services_by_key)

    by_webhook: dict[str, str] = {}
    for wf_path in _git_list_workflows():
        wf = _git_read_workflow(wf_path)
        wp = _webhook_path(wf)
        if not wp:
            continue
        sk = _service_key_from_webhook(wp, known_keys)
        if sk:
            by_webhook[wp] = sk

    updated = 0
    for wf_path in _git_list_workflows():
        wf = _git_read_workflow(wf_path)
        wp = _webhook_path(wf)
        if not wp:
            continue
        sk = _service_key_from_webhook(wp, known_keys)
        if not sk or sk not in services_by_key:
            continue
        row = services_by_key[sk]
        channel = row.get("channel")
        if channel == "whatsapp":
            tn = _template_name_from_workflow(wf, sk)
            if tn and not (row.get("template_name") or "").strip():
                row["template_name"] = tn
                updated += 1
            if not row.get("template_variables"):
                # default single-body binding for common patterns
                if sk == "whatapi-otp" or "otp" in sk:
                    row["template_variables"] = ["{{otp}}"]
                elif row.get("template_variables") is None:
                    row["template_variables"] = ["{{first_name}}"]
        elif channel == "email":
            subj, body, html = _email_content_from_workflow(wf)
            if subj and "{{" not in subj and not (row.get("email_subject") or "").strip():
                row["email_subject"] = subj
                updated += 1
            if html and "{{" not in html and not (row.get("email_html") or "").strip():
                row["email_html"] = html
            if body and "{{" not in body and not (row.get("email_body") or "").strip():
                row["email_body"] = body

    # Ensure every active service has minimal content for direct send
    for sk, row in services_by_key.items():
        if not row.get("is_active", True):
            continue
        ch = row.get("channel")
        if ch == "whatsapp" and not (row.get("template_name") or "").strip():
            row["template_name"] = _template_name_from_workflow({}, sk) or sk.split("-")[0]
            row.setdefault("template_variables", ["{{first_name}}"])
            updated += 1
        if ch == "email" and not (row.get("email_subject") or "").strip():
            row["email_subject"] = row.get("display_name") or sk
            row["email_body"] = row.get("email_body") or "Hello {{first_name}},\n\nThis is a notification from SuperShyft."
            row["email_html"] = (
                row.get("email_html")
                or "<p>Hello {{first_name}},</p><p>This is a notification from SuperShyft.</p>"
            )
            updated += 1

    out_list = [services_by_key[k] for k in sorted(services_by_key)]
    OUT_SERVICES.parent.mkdir(parents=True, exist_ok=True)
    OUT_SERVICES.write_text(json.dumps(out_list, indent=2), encoding="utf-8")
    filled = sum(
        1
        for s in out_list
        if (s.get("template_name") or "").strip()
        or (s.get("email_subject") or "").strip()
    )
    print(f"Wrote {OUT_SERVICES}: {len(out_list)} services, {filled} with content ({updated} updates)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
