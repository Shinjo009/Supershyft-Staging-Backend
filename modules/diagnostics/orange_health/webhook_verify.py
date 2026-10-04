"""Orange Health webhook signature verification."""

from __future__ import annotations

import hashlib
import hmac

from core.exceptions import AppError


def verify_orange_health_webhook_signature(
    raw_body: bytes,
    signature: str | None,
    secret: str,
) -> None:
    """Verify X-OH-Signature (HMAC-SHA256 over raw request body)."""
    key = (secret or "").strip()
    if not key:
        raise AppError(
            status_code=401,
            error_code="AUTH_FAILED",
            message="Orange Health webhook secret is not configured",
        )

    received = (signature or "").strip()
    if not received:
        raise AppError(
            status_code=401,
            error_code="AUTH_FAILED",
            message="Invalid or missing X-OH-Signature",
        )

    expected = hmac.new(key.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise AppError(
            status_code=401,
            error_code="AUTH_FAILED",
            message="Invalid or missing X-OH-Signature",
        )
