"""PII masking helpers for API responses."""

from __future__ import annotations


def looks_masked(value: str | None) -> bool:
    """True when a contact string already contains redaction asterisks."""
    if value is None:
        return False
    return "*" in str(value)


def mask_phone(phone: str | None) -> str | None:
    """Mask a phone number, keeping the last 4 characters visible.

    Example: ``9600004773`` → ``******4773``. Null/empty stays as-is.
    """
    if phone is None:
        return None
    value = str(phone)
    if not value:
        return value
    if len(value) <= 4:
        return value
    return ("*" * (len(value) - 4)) + value[-4:]


def mask_email(email: str | None) -> str | None:
    """Mask the local-part of an email for admin display.

    Keeps the first character and last 3 characters of the local-part, plus the
    full domain.

    Example: ``sandeeprairai199@gmail.com`` → ``s***********199@gmail.com``.
    Null/empty or emails without ``@`` are handled safely.
    """
    if email is None:
        return None
    value = str(email)
    if not value:
        return value

    at = value.rfind("@")
    if at <= 0:
        return mask_phone(value)

    local = value[:at]
    domain = value[at:]  # includes '@'
    if len(local) <= 4:
        return ("*" * len(local)) + domain
    return local[0] + ("*" * (len(local) - 4)) + local[-3:] + domain
