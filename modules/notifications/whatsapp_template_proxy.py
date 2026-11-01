"""Normalize WhatAPI message template fetch for admin UI."""

from __future__ import annotations

from typing import Any

from modules.notifications.whatapi_client import fetch_message_template, template_language_code


def _component_summary(components: list | None) -> list[dict[str, Any]]:
    if not isinstance(components, list):
        return []
    out: list[dict[str, Any]] = []
    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_type = str(comp.get("type") or "").upper()
        fmt = str(comp.get("format") or "").upper()
        example = comp.get("example")
        param_count = 0
        if isinstance(example, dict):
            body_text = example.get("body_text")
            if isinstance(body_text, list) and body_text:
                first = body_text[0]
                if isinstance(first, list):
                    param_count = len(first)
                elif isinstance(first, str):
                    param_count = 1
            header_text = example.get("header_text")
            if isinstance(header_text, list):
                param_count = max(param_count, len(header_text))
        out.append(
            {
                "type": comp_type,
                "format": fmt or None,
                "parameter_count": param_count,
            }
        )
    return out


async def fetch_whatsapp_template_for_admin(name: str) -> dict[str, Any] | None:
    raw = await fetch_message_template(name.strip())
    if not raw:
        return None
    status = str(raw.get("status") or "").upper()
    return {
        "name": raw.get("name") or name,
        "language": template_language_code(raw),
        "category": raw.get("category"),
        "status": status,
        "components": _component_summary(raw.get("components")),
        "raw": raw,
    }
