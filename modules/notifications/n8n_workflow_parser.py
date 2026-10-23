"""Parse n8n workflow JSON (git e543900 shape) into notification service content."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

_PREPARE_NAME_RE = re.compile(
    r"prepare",
    re.IGNORECASE,
)
_MESSAGE_ASSIGN_RE = re.compile(
    r"const\s+message\s*=\s*(.+?);\s*(?:return|\n)",
    re.DOTALL | re.IGNORECASE,
)
_TEMPLATE_LITERAL_RE = re.compile(r"`([^`]*)`")
_DISPATCH_URL_RE = re.compile(r"/notifications/dispatch", re.IGNORECASE)
_SERVICE_KEY_IN_BODY_RE = re.compile(
    r"""['"]service_key['"]\s*:\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)
_VAR_MAP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(name|agentName|first_name)$", re.I), "{{first_name}}"),
    (re.compile(r"otp", re.I), "{{otp}}"),
    (re.compile(r"collectionDate|collection_date|bookingDate", re.I), "{{session_details.date}}"),
    (re.compile(r"collectionTime|collection_time|bookingTime", re.I), "{{session_details.slot}}"),
    (re.compile(r"cabinName|cabin_name|cabinRaw", re.I), "{{session_details.cabin}}"),
    (re.compile(r"detailsName", re.I), "{{participant_details.name}}"),
    (re.compile(r"detailsPhone", re.I), "{{participant_details.phone}}"),
    (re.compile(r"detailsEmail", re.I), "{{participant_details.email}}"),
    (re.compile(r"blood_report|report_url", re.I), "{{blood_report_url}}"),
    (re.compile(r"bio_ai|bioai", re.I), "{{bio_ai_report_url}}"),
    (re.compile(r"external_link|gift_url", re.I), "{{external_link}}"),
]


@dataclass
class ParsedWorkflowContent:
    webhook_path: str | None = None
    channel: str | None = None
    template_name: str | None = None
    template_variables: list[Any] | None = None
    email_subject: str | None = None
    email_body: str | None = None
    email_html: str | None = None


@dataclass
class ParsedWorkflow:
    workflow_file: str | None = None
    webhook_path: str | None = None
    primary: ParsedWorkflowContent | None = None
    email: ParsedWorkflowContent | None = None
    chained_dispatches: list[dict[str, Any]] = field(default_factory=list)


def _map_js_var(expr: str) -> str:
    expr = expr.strip()
    if re.search(r"first_name|agentName|^name$", expr, re.I):
        return "{{first_name}}"
    if re.search(r"detailsName|pd\.name|participant.*name", expr, re.I):
        return "{{participant_details.name}}"
    for pattern, binding in _VAR_MAP:
        if pattern.search(expr):
            return binding
    return "{{first_name}}"


def _expand_embedded_js_vars(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        return _map_js_var(m.group(1))

    return re.sub(r"\$\{([^}]+)\}", repl, text)


def _normalize_message_expr(expr: str) -> str:
    text = expr.strip()
    text = re.sub(r"\s*\+\s*`", "`", text)
    text = re.sub(r"`\s*\+\s*`", "", text)
    text = re.sub(r"`\s*\+\s*", "", text)
    literals = _TEMPLATE_LITERAL_RE.findall(text)
    if literals:
        return "".join(literals)
    return text.strip("`\"'")


def _split_message_body_segments(rest: str) -> list[str]:
    """Split comma-separated body segments; commas inside ${...} do not split."""
    segments: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(rest):
        ch = rest[i]
        if ch == "$" and rest[i : i + 2] == "${":
            j = rest.find("}", i)
            if j < 0:
                buf.append(rest[i:])
                break
            buf.append(rest[i : j + 1])
            i = j + 1
            continue
        if ch == ",":
            seg = "".join(buf).strip()
            if seg:
                segments.append(seg)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        segments.append(tail)
    return segments


def _segment_to_variable(segment: str) -> Any:
    segment = segment.strip()
    if segment.startswith("${") and segment.endswith("}"):
        return _map_js_var(segment[2:-1])
    expanded = _expand_embedded_js_vars(segment)
    if "{{" in expanded:
        return expanded
    return segment


def _parse_comma_message(message: str) -> tuple[str | None, list[Any]]:
    message = message.strip()
    if not message:
        return None, []
    first_comma = message.find(",")
    if first_comma < 0:
        return message, []
    template_name = message[:first_comma].strip()
    rest = message[first_comma + 1 :]
    variables = [_segment_to_variable(s) for s in _split_message_body_segments(rest)]
    return template_name, variables


def parse_whatsapp_message_from_js(js_code: str) -> tuple[str | None, list[Any] | None]:
    match = _MESSAGE_ASSIGN_RE.search(js_code)
    if not match:
        return None, None
    normalized = _normalize_message_expr(match.group(1))
    template_name, variables = _parse_comma_message(normalized)
    if not template_name:
        return None, None
    if template_name in ("otp", "otpmsg") and variables and variables[0] == "{{first_name}}":
        variables[0] = "{{otp}}"
    return template_name, variables or None


def _parse_email_from_js(js_code: str) -> tuple[str | None, str | None, str | None]:
    subject = None
    body = None
    html = None
    subj_m = re.search(r"const\s+subject\s*=\s*[`'\"]([^`'\"]*)[`'\"]", js_code, re.I)
    if subj_m:
        subject = subj_m.group(1).strip()
    if not subject:
        subj_m2 = re.search(r"subject\s*:\s*['\"]([^'\"]+)['\"]", js_code, re.I)
        if subj_m2:
            subject = subj_m2.group(1).strip()
    body_m = re.search(
        r"const\s+(?:body|htmlBody|html)\s*=\s*`([^`]*)`",
        js_code,
        re.I | re.DOTALL,
    )
    if body_m:
        text = body_m.group(1)
        if "<html" in text.lower() or "<p" in text.lower() or "<!DOCTYPE" in text.upper():
            html = text
        else:
            body = text
    return subject, body, html


def find_chained_dispatches(workflow: dict) -> list[dict[str, Any]]:
    chains: list[dict[str, Any]] = []
    for node in workflow.get("nodes", []):
        if "httpRequest" not in (node.get("type") or ""):
            continue
        params = node.get("parameters") or {}
        url = str(params.get("url") or "")
        if not _DISPATCH_URL_RE.search(url):
            continue
        entry: dict[str, Any] = {"node_name": node.get("name"), "url": url}
        body = params.get("jsonBody") or params.get("body") or ""
        if isinstance(body, str):
            sk = _SERVICE_KEY_IN_BODY_RE.search(body)
            if sk:
                entry["service_key"] = sk.group(1)
            try:
                entry["body"] = json.loads(body)
            except json.JSONDecodeError:
                entry["body_raw"] = body[:500]
        chains.append(entry)
    return chains


def webhook_path_from_workflow(workflow: dict) -> str | None:
    for node in workflow.get("nodes", []):
        if "webhook" in (node.get("type") or "").lower():
            path = (node.get("parameters") or {}).get("path")
            if path:
                return str(path).strip().lstrip("/")
    return None


def _prepare_nodes(workflow: dict) -> list[dict]:
    nodes: list[dict] = []
    for node in workflow.get("nodes", []):
        name = node.get("name") or ""
        js = (node.get("parameters") or {}).get("jsCode") or ""
        if not js:
            continue
        if _PREPARE_NAME_RE.search(name) or "message" in js.lower():
            nodes.append(node)
    return nodes


def parse_workflow(workflow: dict, *, workflow_file: str | None = None) -> ParsedWorkflow:
    result = ParsedWorkflow(
        workflow_file=workflow_file,
        webhook_path=webhook_path_from_workflow(workflow),
        chained_dispatches=find_chained_dispatches(workflow),
    )
    whatsapp: ParsedWorkflowContent | None = None
    email: ParsedWorkflowContent | None = None

    for node in _prepare_nodes(workflow):
        js = (node.get("parameters") or {}).get("jsCode") or ""
        name = (node.get("name") or "").lower()
        tn, tv = parse_whatsapp_message_from_js(js)
        if tn and (whatsapp is None or "whatsapp" in name or "booking message" in name):
            if whatsapp is None or "email" not in name:
                whatsapp = ParsedWorkflowContent(
                    channel="whatsapp",
                    template_name=tn,
                    template_variables=tv,
                )
        subj, body, html = _parse_email_from_js(js)
        if subj or body or html or "email" in name:
            if email is None or "email" in name:
                email = ParsedWorkflowContent(
                    channel="email",
                    email_subject=subj,
                    email_body=body,
                    email_html=html,
                )

    for node in workflow.get("nodes", []):
        if "emailSend" not in (node.get("type") or ""):
            continue
        p = node.get("parameters") or {}
        subj = str(p.get("subject") or "").strip()
        if subj.startswith("="):
            subj = ""
        html = str(p.get("html") or p.get("htmlBody") or "").strip()
        body = str(p.get("text") or p.get("message") or "").strip()
        if not email:
            email = ParsedWorkflowContent(channel="email")
        if subj and not email.email_subject:
            email.email_subject = subj
        if html and not email.email_html:
            email.email_html = html
        if body and not email.email_body:
            email.email_body = body

    if whatsapp:
        whatsapp.webhook_path = result.webhook_path
        result.primary = whatsapp
    elif email:
        email.webhook_path = result.webhook_path
        result.primary = email
    result.email = email
    return result


def parse_workflow_file(workflow: dict, workflow_path: str) -> ParsedWorkflow:
    return parse_workflow(workflow, workflow_file=workflow_path)


def parse_prepare_node(
    workflow: dict,
    *,
    name_contains: str,
) -> ParsedWorkflowContent | None:
    needle = name_contains.lower()
    for node in _prepare_nodes(workflow):
        name = (node.get("name") or "").lower()
        if needle not in name:
            continue
        js = (node.get("parameters") or {}).get("jsCode") or ""
        tn, tv = parse_whatsapp_message_from_js(js)
        if tn:
            return ParsedWorkflowContent(
                channel="whatsapp",
                template_name=tn,
                template_variables=tv,
            )
        subj, body, html = _parse_email_from_js(js)
        if subj or body or html:
            return ParsedWorkflowContent(
                channel="email",
                email_subject=subj,
                email_body=body,
                email_html=html,
            )
    return None
