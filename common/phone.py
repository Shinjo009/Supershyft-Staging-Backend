"""Shared phone normalization for matching stored user.phone values."""

from __future__ import annotations

from core.exceptions import AppError

_ALLOWED_SYMBOLS = frozenset("0123456789+ -()")
_MIN_DIGITS = 8


def _extract_digits(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())


def _validate_phone_raw(phone: str | None, *, strict: bool) -> str | None:
    """Return stripped raw phone or None/raise when invalid."""
    raw = (phone or "").strip()
    if not raw:
        if strict:
            raise AppError(status_code=400, error_code="INVALID_INPUT", message="Invalid request")
        return None

    if any(ch not in _ALLOWED_SYMBOLS for ch in raw):
        if strict:
            raise AppError(status_code=400, error_code="INVALID_INPUT", message="Invalid request")
        return None

    digits = _extract_digits(raw)
    if len(digits) < _MIN_DIGITS:
        if strict:
            raise AppError(status_code=400, error_code="INVALID_INPUT", message="Invalid request")
        return None
    return raw


def normalize_phone_for_storage(phone: str | None, *, strict: bool = False) -> str | None:
    """Return one canonical E.164-style phone for employee/partner storage.

    Indian 10-digit (and 0… / 91… / +91… variants) → ``+91XXXXXXXXXX``.
    Other lengths → ``+{digits}``. Empty/None → None. Invalid → raise when
    ``strict`` else None.
    """
    raw = _validate_phone_raw(phone, strict=strict)
    if raw is None:
        return None

    digits = _extract_digits(raw)

    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+91{digits[2:]}"
    if len(digits) == 11 and digits.startswith("0"):
        return f"+91{digits[1:]}"
    return f"+{digits}"


def phone_lookup_candidates(phone: str, *, strict: bool = False) -> list[str]:
    """Build ordered unique phone strings to match stored user.phone values.

    Supports Indian local (+91) forms and international E.164-style numbers
    (e.g. +66961275268). Always includes the canonical storage form first when
    it can be derived.

    When ``strict`` is True, invalid input raises ``AppError`` (400).
    Otherwise invalid input returns an empty list.
    """

    raw = _validate_phone_raw(phone, strict=strict)
    if raw is None:
        return []

    stripped = raw.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    digits = _extract_digits(raw)

    ordered: list[str] = []

    def _add(*values: str) -> None:
        for value in values:
            if value and value not in ordered:
                ordered.append(value)

    canonical = normalize_phone_for_storage(raw, strict=False)
    if canonical:
        _add(canonical)

    _add(raw, stripped)

    if len(digits) == 10:
        _add(digits, f"+91{digits}", f"91{digits}")
    elif len(digits) == 12 and digits.startswith("91"):
        base10 = digits[2:]
        _add(base10, f"+91{base10}", f"91{base10}", f"+{digits}")
    elif len(digits) == 11 and digits.startswith("0"):
        base10 = digits[1:]
        _add(base10, f"+91{base10}", f"91{base10}")
    else:
        _add(f"+{digits}", digits)

    return ordered


def to_healthians_mobile(phone: str | None) -> str:
    """Return last 10 digits for Healthians mobile/calling fields."""
    digits = _extract_digits(phone or "")
    if len(digits) >= 10:
        return digits[-10:]
    return digits
