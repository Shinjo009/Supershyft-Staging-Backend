"""Parse n8n workflow JSON into notification_services direct-delivery content."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from db.seed.data import DEFAULT_NOTIFICATION_SERVICES

_WEBHOOK_PATH_TO_SERVICE_KEY: dict[str, str] = {
    svc.webhook_path.lstrip("/"): svc.service_key for svc in DEFAULT_NOTIFICATION_SERVICES
}

_MESSAGE_TEMPLATE_RE = re.compile(
    r"(?:const\s+message\s*=|`message`\s*=)\s*(?:\n`|\s*`)([\s\S]*?)`\s*;",
    re.MULTILINE,
)
_PREPARE_EMAIL_SUBJECT_RE = re.compile(
    r"subject:\s*['\"]([^'\"]+)['\"]|subject:\s*`([^`]+)`",
    re.IGNORECASE,
)
_PREPARE_EMAIL_BODY_RE = re.compile(
    r"body:\s*['\"]([^'\"]+)['\"]|body:\s*`([^`]+)`|htmlBody:\s*`([^`]+)`",
    re.IGNORECASE,
)


@dataclass
class ParsedServiceContent:
    service_key: str | None
    webhook_path: str
    workflow_file: str
    channel: str
    template_name: str | None = None
    template_variables: list[dict[str, Any]] | None = None
    email_subject: str | None = None
    email_body: str | None = None
    email_html: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class MigrationReport:
    services: list[ParsedServiceContent]
    unmatched_webhook_paths: list[str]
    warnings: list[str]


def infer_service_key(webhook_path: str, workflow_filename: str) -> str | None:
    key = _WEBHOOK_PATH_TO_SERVICE_KEY.get(webhook_path.strip("/"))
    if key:
        return key
    stem = workflow_filename.replace(".json", "")
    return stem


def _normalize_webhook_path(raw: str) -> str:
    return raw.strip().lstrip("/")


def _extract_webhook_path(nodes: list[dict]) -> str | None:
    for node in nodes:
        if node.get("type") != "n8n-nodes-base.webhook":
            continue
        path = (node.get("parameters") or {}).get("path")
        if isinstance(path, str) and path.strip():
            return _normalize_webhook_path(path)
    return None


def _infer_var_ref(js_code: str, var_name: str) -> str | None:
    patterns: list[tuple[str, str]] = [
        (rf"const {re.escape(var_name)}\s*=\s*\(member\.first_name", "member.first_name"),
        (rf"const {re.escape(var_name)}\s*=\s*String\(member\.otp", "member.otp"),
        (rf"const {re.escape(var_name)}\s*=\s*\(member\.session_details\?\.date", "member.session_details.date"),
        (rf"const {re.escape(var_name)}\s*=\s*\(member\.session_details\?\.slot", "member.session_details.slot"),
        (rf"const {re.escape(var_name)}\s*=\s*\(cabinRaw", "member.session_details.cabin"),
        (rf"const {re.escape(var_name)}\s*=\s*\(cabinName", "member.session_details.cabin"),
        (rf"const {re.escape(var_name)}\s*=\s*\(member\.blood_report_url", "member.blood_report_url"),
        (rf"const {re.escape(var_name)}\s*=\s*\(member\.bio_ai_report_url", "member.bio_ai_report_url"),
        (rf"const {re.escape(var_name)}\s*=\s*\(member\.external_link", "member.external_link"),
        (rf"const {re.escape(var_name)}\s*=\s*\(pd\.phlebo_name", "participant_details.phlebo_name"),
        (rf"const {re.escape(var_name)}\s*=\s*\(pd\.masked_number", "participant_details.masked_number"),
        (rf"const {re.escape(var_name)}\s*=\s*\(pd\.tracking_url", "participant_details.tracking_url"),
        (rf"const {re.escape(var_name)}\s*=\s*pd\.eta_in_minutes", "participant_details.eta_in_minutes"),
        (rf"const {re.escape(var_name)}\s*=\s*\(sd\.date", "member.session_details.date"),
        (rf"const {re.escape(var_name)}\s*=\s*\(sd\.slot", "member.session_details.slot"),
        (rf"const {re.escape(var_name)}\s*=\s*\(sd\.cabin", "member.session_details.cabin"),
        (rf"const {re.escape(var_name)}\s*=\s*\(member\.email", "member.email"),
    ]
    for pattern, ref in patterns:
        if re.search(pattern, js_code):
            return ref
    if var_name in {"name", "first_name", "cabinName", "collectionDate", "collectionTime"}:
        ref_map = {
            "name": "member.first_name",
            "first_name": "member.first_name",
            "cabinName": "member.session_details.cabin",
            "collectionDate": "member.session_details.date",
            "collectionTime": "member.session_details.slot",
        }
        if var_name in ref_map:
            return ref_map[var_name]
    if var_name == "otp":
        return "member.otp"
    return None


def _split_template_segments(template_inner: str) -> list[str]:
    """Split comma-separated WhatsApp GET message segments respecting ${...}."""
    segments: list[str] = []
    buf: list[str] = []
    depth = 0
    i = 0
    while i < len(template_inner):
        ch = template_inner[i]
        if ch == "$" and i + 1 < len(template_inner) and template_inner[i + 1] == "{":
            depth += 1
            buf.append("${")
            i += 2
            while i < len(template_inner) and depth:
                if template_inner[i : i + 2] == "${":
                    depth += 1
                    buf.append("${")
                    i += 2
                    continue
                if template_inner[i] == "}":
                    depth -= 1
                    buf.append("}")
                    i += 1
                    continue
                buf.append(template_inner[i])
                i += 1
            continue
        if ch == "," and depth == 0:
            segments.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if buf:
        segments.append("".join(buf).strip())
    return [s for s in segments if s]


def _segment_to_parameter(segment: str, js_code: str) -> dict[str, Any]:
    segment = segment.strip()
    if not segment:
        return {"type": "text", "literal": ""}

    pure_var = re.match(r"^\$\{([^}]+)\}$", segment)
    if pure_var:
        var = pure_var.group(1).strip()
        ref = _infer_var_ref(js_code, var.split(".")[0]) or _infer_var_ref(js_code, var)
        if ref:
            return {"type": "text", "ref": ref}
        return {"type": "text", "literal": segment}

    parts = re.split(r"(\$\{[^}]+\})", segment)
    if len(parts) == 1 and parts[0].startswith("${") and parts[0].endswith("}"):
        var = parts[0][2:-1].strip()
        ref = _infer_var_ref(js_code, var.split(".")[0]) or _infer_var_ref(js_code, var)
        if ref:
            return {"type": "text", "ref": ref}
        return {"type": "text", "literal": segment}

    if "${" not in segment:
        return {"type": "text", "literal": segment}

    # Mixed literal + expression → interpolate via source string
    source = segment
    for match in re.finditer(r"\$\{([^}]+)\}", segment):
        var = match.group(1).strip()
        ref = _infer_var_ref(js_code, var.split(".")[0]) or _infer_var_ref(js_code, var)
        if ref:
            source = source.replace(match.group(0), "{{" + ref + "}}")
    if "{{" in source:
        return {"type": "text", "source": source}
    return {"type": "text", "literal": segment}


def _parse_whatsapp_message(js_code: str) -> tuple[str | None, list[dict[str, Any]] | None]:
    match = _MESSAGE_TEMPLATE_RE.search(js_code)
    if not match:
        return None, None
    inner = match.group(1).replace("\\n", "\n").strip()
    segments = _split_template_segments(inner)
    if not segments:
        return None, None
    template_name = segments[0].strip()
    body_segments = segments[1:]
    parameters = [_segment_to_parameter(seg, js_code) for seg in body_segments]
    return template_name, parameters


def _has_document_attachment(js_code: str) -> str | None:
    if "blood_report_url" in js_code:
        return "member.blood_report_url"
    if "bio_ai_report_url" in js_code:
        return "member.bio_ai_report_url"
    return None


def _build_template_variables(js_code: str) -> tuple[str | None, list[dict[str, Any]] | None]:
    template_name, body_params = _parse_whatsapp_message(js_code)
    if not template_name or body_params is None:
        return None, None
    components: list[dict[str, Any]] = []
    doc_ref = _has_document_attachment(js_code)
    if doc_ref:
        components.append(
            {
                "component": "header",
                "parameters": [{"type": "document", "link": {"ref": doc_ref}}],
            }
        )
    components.append({"component": "body", "parameters": body_params})
    return template_name, components


def _js_template_to_email_source(template: str, js_code: str) -> str:
    result = template
    for match in re.finditer(r"\$\{([^}]+)\}", template):
        var = match.group(1).strip()
        ref = _infer_var_ref(js_code, var.split(".")[0]) or _infer_var_ref(js_code, var)
        if ref:
            result = result.replace(match.group(0), "{{" + ref + "}}")
    return result


def _extract_email_literals_from_code_nodes(nodes: list[dict]) -> tuple[str | None, str | None, str | None]:
    subject: str | None = None
    body: str | None = None
    html: str | None = None
    for node in nodes:
        if node.get("type") != "n8n-nodes-base.code":
            continue
        js = (node.get("parameters") or {}).get("jsCode") or ""
        sm = re.search(r"subject:\s*['\"]([^'\"]+)['\"]", js)
        if sm:
            subject = sm.group(1).strip()
        bm = re.search(r"const body = `([\s\S]*?)`", js)
        if bm:
            body = _js_template_to_email_source(bm.group(1), js)
        hm = re.search(r"const htmlBody = `([\s\S]*?)`", js)
        if hm:
            html = _js_template_to_email_source(hm.group(1), js)
        if not body:
            bm2 = _PREPARE_EMAIL_BODY_RE.search(js)
            if bm2:
                body = (bm2.group(1) or bm2.group(2) or "").strip()
    return subject, body, html


def _extract_email_from_nodes(nodes: list[dict]) -> tuple[str | None, str | None, str | None]:
    subject, body, html = _extract_email_literals_from_code_nodes(nodes)
    if subject or body or html:
        return subject, body, html
    for node in nodes:
        if node.get("type") != "n8n-nodes-base.emailSend":
            continue
        params = node.get("parameters") or {}
        subject_expr = str(params.get("subject") or "").strip()
        text_expr = str(params.get("text") or "").strip()
        html_expr = str(params.get("html") or "").strip() or None
        if subject_expr.startswith("={{") and text_expr.startswith("={{ $json.body"):
            return None, None, html_expr
        return subject_expr or None, text_expr or None, html_expr
    return None, None, None


def _workflow_has_whatsapp_message(nodes: list[dict]) -> bool:
    for node in nodes:
        js = (node.get("parameters") or {}).get("jsCode") or ""
        if "const message" in js or "message =" in js:
            if "camp" in js or "otp," in js or "`otp," in js:
                return True
    return False


def parse_workflow_file(path: Path) -> ParsedServiceContent | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    nodes = data.get("nodes") or []
    if not isinstance(nodes, list):
        return None
    webhook_path = _extract_webhook_path(nodes)
    if not webhook_path:
        return None

    service_key = infer_service_key(webhook_path, path.name)
    warnings: list[str] = []
    if not service_key:
        warnings.append("could not infer service_key")

    has_email = any(n.get("type") == "n8n-nodes-base.emailSend" for n in nodes)
    if _workflow_has_whatsapp_message(nodes):
        channel = "whatsapp"
    elif has_email:
        channel = "email"
    else:
        channel = "whatsapp"
    parsed = ParsedServiceContent(
        service_key=service_key,
        webhook_path=webhook_path,
        workflow_file=path.name,
        channel=channel,
        warnings=warnings,
    )

    for node in nodes:
        js = (node.get("parameters") or {}).get("jsCode") or ""
        if not js:
            continue
        if channel == "whatsapp" and ("const message" in js or "message =" in js):
            template_name, template_variables = _build_template_variables(js)
            if template_name:
                parsed.template_name = template_name
                parsed.template_variables = template_variables
                break

    if channel == "email":
        subject, body, html = _extract_email_from_nodes(nodes)
        parsed.email_subject = subject
        parsed.email_body = body
        parsed.email_html = html
        if not subject and not body:
            for node in nodes:
                js = (node.get("parameters") or {}).get("jsCode") or ""
                sm = _PREPARE_EMAIL_SUBJECT_RE.search(js)
                bm = _PREPARE_EMAIL_BODY_RE.search(js)
                if sm:
                    parsed.email_subject = (sm.group(1) or sm.group(2) or "").strip()
                if bm:
                    parsed.email_body = (bm.group(1) or bm.group(2) or bm.group(3) or "").strip()
                if parsed.email_subject or parsed.email_body:
                    break

    if channel == "whatsapp" and not parsed.template_name:
        parsed.warnings.append("no WhatsApp message template found")
    if channel == "email" and not parsed.email_subject and not parsed.email_body:
        parsed.warnings.append("no email subject/body found")

    return parsed


def parse_workflows_dir(workflows_dir: Path) -> MigrationReport:
    services: list[ParsedServiceContent] = []
    unmatched: list[str] = []
    all_warnings: list[str] = []
    for path in sorted(workflows_dir.glob("*.json")):
        parsed = parse_workflow_file(path)
        if parsed is None:
            continue
        services.append(parsed)
        if not parsed.service_key:
            unmatched.append(parsed.webhook_path)
        all_warnings.extend(f"{parsed.workflow_file}: {w}" for w in parsed.warnings)
    return MigrationReport(services=services, unmatched_webhook_paths=unmatched, warnings=all_warnings)


def service_content_to_db_row(parsed: ParsedServiceContent) -> dict[str, Any] | None:
    if not parsed.service_key:
        return None
    row: dict[str, Any] = {
        "service_key": parsed.service_key,
        "webhook_path": f"/{parsed.webhook_path}",
    }
    if parsed.template_name:
        row["template_name"] = parsed.template_name
        row["template_variables"] = parsed.template_variables or []
    if parsed.email_subject:
        row["email_subject"] = parsed.email_subject
    if parsed.email_body:
        row["email_body"] = parsed.email_body
    if parsed.email_html:
        row["email_html"] = parsed.email_html
    if "template_name" not in row and not parsed.email_subject and not parsed.email_body:
        return None
    return row


def build_content_artifact(workflows_dir: Path) -> list[dict[str, Any]]:
    report = parse_workflows_dir(workflows_dir)
    by_key: dict[str, dict[str, Any]] = {}
    for parsed in report.services:
        row = service_content_to_db_row(parsed)
        if row is None:
            continue
        existing = by_key.get(row["service_key"])
        if existing is None:
            by_key[row["service_key"]] = row
            continue
        # Prefer entry with more template params / email fields
        if row.get("template_variables") and not existing.get("template_variables"):
            by_key[row["service_key"]] = row
    return list(by_key.values())


def body_parameter_count(template_variables: list | None) -> int:
    if not template_variables:
        return 0
    for block in template_variables:
        if isinstance(block, dict) and block.get("component") == "body":
            params = block.get("parameters") or []
            return len(params) if isinstance(params, list) else 0
    return 0
