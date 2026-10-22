"""Resolve {{path}} placeholders in notification content bindings."""

from __future__ import annotations

import re
from typing import Any

_PLACEHOLDER_RE = re.compile(r"^\{\{(.+)\}\}$")


def _get_path_value(context: dict[str, Any], path: str) -> Any:
    parts = [p.strip() for p in path.split(".") if p.strip()]
    current: Any = context
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def resolve_binding_value(binding: Any, context: dict[str, Any]) -> str:
    """Resolve a single template_variables binding to a string."""
    if isinstance(binding, dict):
        if binding.get("type") == "header_document":
            raw = binding.get("value", "")
            return resolve_text(str(raw), context)
        return str(binding)

    text = str(binding)
    return resolve_text(text, context)


def resolve_text(text: str, context: dict[str, Any]) -> str:
    """Replace {{dot.path}} placeholders in text; leave other text literal."""
    match = _PLACEHOLDER_RE.match(text.strip())
    if match:
        value = _get_path_value(context, match.group(1))
        return "" if value is None else str(value)

    def repl(m: re.Match[str]) -> str:
        value = _get_path_value(context, m.group(1))
        return "" if value is None else str(value)

    return re.sub(r"\{\{([^}]+)\}\}", repl, text)


def build_dispatch_context(
    member: dict[str, Any],
    *,
    participant_details: dict | None = None,
    engagement_id: int | None = None,
) -> dict[str, Any]:
    """Flatten member + participant_details for variable resolution."""
    ctx: dict[str, Any] = {
        "first_name": member.get("first_name"),
        "last_name": member.get("last_name"),
        "phone": member.get("phone"),
        "email": member.get("email"),
        "otp": member.get("otp"),
        "blood_report_url": member.get("blood_report_url"),
        "bio_ai_report_url": member.get("bio_ai_report_url"),
        "external_link": member.get("external_link"),
        "session_details": member.get("session_details") or {},
        "participant_details": participant_details or member.get("participant_details") or {},
    }
    if engagement_id is not None:
        ctx["engagement_id"] = engagement_id
    return ctx
