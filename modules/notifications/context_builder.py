"""Build interpolation context from event payloads."""

from __future__ import annotations

from typing import Any


def _merge_bag(target: dict[str, Any], prefix: str, bag: object) -> None:
    if not isinstance(bag, dict):
        return
    nested = target.setdefault(prefix, {})
    if isinstance(nested, dict):
        for key, value in bag.items():
            nested[key] = value


def build_event_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Flatten known variable bags for template ref / email interpolation."""
    ctx: dict[str, Any] = dict(payload)
    user = payload.get("user")
    if isinstance(user, dict):
        _merge_bag(ctx, "user", user)
    elif payload.get("user_id") is not None:
        ctx.setdefault("user", {"user_id": payload.get("user_id")})

    for bag_name in (
        "otp",
        "collection",
        "discount",
        "consultation",
        "report",
        "participant_details",
        "session_details",
        "ticket",
        "engagement",
        "member",
    ):
        if bag_name in payload:
            _merge_bag(ctx, bag_name, payload.get(bag_name))

    otp_val = payload.get("otp")
    if otp_val is not None:
        ctx["otp"] = {"otp": str(otp_val)}

    return ctx
