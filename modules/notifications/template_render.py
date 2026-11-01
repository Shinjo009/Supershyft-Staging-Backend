"""String interpolation for email/event templates using event context."""

from __future__ import annotations

import re
from typing import Any

from modules.notifications.whatsapp_template_builder import _resolve_ref

_PLACEHOLDER = re.compile(r"\{\{(\w+(?:\.\w+)*)\}\}")


def interpolate_template(template: str, context: dict[str, Any]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key == "otp":
            otp_ctx = context.get("otp")
            if isinstance(otp_ctx, dict):
                return str(otp_ctx.get("otp") or "")
            return str(context.get("otp") or "")
        return _resolve_ref(key, context)

    return _PLACEHOLDER.sub(repl, template)
