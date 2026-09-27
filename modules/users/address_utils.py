"""Helpers for composed user address strings (comma-joined line1, line2, landmark)."""

from __future__ import annotations

MAX_USER_ADDRESSES = 3


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def compose_address(
    address_line1: str | None = None,
    address_line2: str | None = None,
    landmark: str | None = None,
) -> str | None:
    parts = [_clean(address_line1), _clean(address_line2), _clean(landmark)]
    joined = ", ".join(part for part in parts if part)
    return joined or None


def split_address(address: str | None) -> tuple[str | None, str | None, str | None]:
    parts = [part.strip() for part in (address or "").split(",") if part.strip()]
    line1 = parts[0] if len(parts) > 0 else None
    line2 = parts[1] if len(parts) > 1 else None
    landmark = parts[2] if len(parts) > 2 else None
    return line1, line2, landmark


def user_has_location(user) -> bool:
    return any(
        _clean(getattr(user, field, None))
        for field in ("address", "city", "state", "pin_code")
    )


def snapshot_from_user(user) -> dict:
    line1, line2, landmark = split_address(getattr(user, "address", None))
    return {
        "address_line1": line1,
        "address_line2": line2,
        "landmark": landmark,
        "city": _clean(getattr(user, "city", None)),
        "state": _clean(getattr(user, "state", None)),
        "pincode": _clean(getattr(user, "pin_code", None)),
        "address": _clean(getattr(user, "address", None)) or compose_address(line1, line2, landmark),
    }
