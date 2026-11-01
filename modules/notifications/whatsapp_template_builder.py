"""Build Meta WhatsApp template components from service template_variables + dispatch context."""

from __future__ import annotations

import re
from typing import Any

_SOURCE_PATTERN = re.compile(r"^\{\{(.+)\}\}$")


def build_dispatch_context(
    members: list[dict],
    *,
    participant_details: dict | None = None,
) -> dict[str, Any]:
    first = members[0] if members else {}
    otp_value = str(first.get("otp") or "").strip()
    ctx: dict[str, Any] = {
        "otp": {"otp": otp_value},
        "member": dict(first),
    }
    if participant_details:
        ctx["participant_details"] = dict(participant_details)
    return ctx


def _resolve_ref(path: str, context: dict[str, Any]) -> str:
    parts = [p.strip() for p in path.split(".") if p.strip()]
    node: Any = context
    for part in parts:
        if not isinstance(node, dict):
            return ""
        node = node.get(part)
    if node is None:
        return ""
    return str(node)


def _resolve_parameter_value(raw: object, context: dict[str, Any]) -> str:
    if isinstance(raw, dict):
        if "literal" in raw:
            return str(raw.get("literal") or "")
        source = raw.get("source")
        if isinstance(source, str):
            match = _SOURCE_PATTERN.match(source.strip())
            if match:
                return _resolve_ref(match.group(1), context)
            return source
        text = raw.get("text")
        if text is not None:
            return str(text)
    return str(raw or "")


def build_template_components(
    template_variables: list | None,
    context: dict[str, Any],
) -> list[dict]:
    """Turn stored template_variables JSON into Meta API template.components."""
    if not template_variables:
        return []
    components: list[dict] = []
    for block in template_variables:
        if not isinstance(block, dict):
            continue
        component_type = str(block.get("component") or block.get("type") or "").strip()
        if not component_type:
            continue
        params_raw = block.get("parameters") or []
        parameters: list[dict] = []
        for param in params_raw if isinstance(params_raw, list) else []:
            if not isinstance(param, dict):
                continue
            param_type = str(param.get("type") or "text").strip()
            if param_type == "document" and param.get("link"):
                parameters.append(
                    {
                        "type": "document",
                        "document": {"link": str(param.get("link"))},
                    }
                )
                continue
            text_value = _resolve_parameter_value(param, context)
            parameters.append({"type": param_type, "text": text_value})
        comp: dict[str, Any] = {"type": component_type.lower(), "parameters": parameters}
        sub_type = block.get("sub_type")
        if sub_type:
            comp["sub_type"] = sub_type
        if block.get("index") is not None:
            comp["index"] = block.get("index")
        components.append(comp)
    return components


def build_template_message_body(
    *,
    to_phone: str,
    template_name: str,
    language_code: str,
    components: list[dict],
) -> dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"policy": "deterministic", "code": language_code},
            "components": components,
        },
    }
