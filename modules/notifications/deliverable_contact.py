"""Heuristics for notification destinations that should not be sent externally."""

from __future__ import annotations

# Domains used in tests/stubs — SMTP may accept but no real inbox exists.
_NON_DELIVERABLE_EMAIL_DOMAINS: frozenset[str] = frozenset(
    {
        "example.com",
        "example.org",
        "example.net",
        "test",
        "invalid",
        "localhost",
    }
)


def is_deliverable_email(email: str | None) -> bool:
    text = (email or "").strip().lower()
    if not text or "@" not in text:
        return False
    local, _, domain = text.partition("@")
    if not local or not domain or "." not in domain:
        return False
    if domain in _NON_DELIVERABLE_EMAIL_DOMAINS:
        return False
    if domain.endswith(".example") or domain.endswith(".test"):
        return False
    if local.startswith("bot-") and domain == "example.com":
        return False
    return True