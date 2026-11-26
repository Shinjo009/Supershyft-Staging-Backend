"""Orange Health cancel partner body and sync-log helpers."""

from __future__ import annotations

from typing import Any

from core.exceptions import AppError

from modules.diagnostics.orange_health.reschedule_helpers import (
    build_orange_reschedule_query_log,
    token_suffix,
)

ORANGE_CANCEL_PARTNER_KEYS = frozenset(
    {"cancellationReason", "cancellationExplanation"}
)


def build_orange_cancel_partner_body(
    *,
    cancellation_reason: str,
    cancellation_explanation: str = "",
) -> dict[str, str]:
    reason = (cancellation_reason or "").strip()
    explanation = (cancellation_explanation or "").strip()
    if not reason:
        raise AppError(
            status_code=422,
            error_code="INVALID_CANCELLATION_REASON",
            message="Cancellation reason is required",
        )
    return {
        "cancellationReason": reason,
        "cancellationExplanation": explanation,
    }


def sanitize_orange_cancel_patch_body(payload: dict[str, Any]) -> dict[str, str]:
    """Keep only Orange Partner cancel JSON body fields."""
    return build_orange_cancel_partner_body(
        cancellation_reason=str(payload.get("cancellationReason", "")),
        cancellation_explanation=str(payload.get("cancellationExplanation", "")),
    )


def build_orange_cancel_query_log(token: str | None) -> dict[str, str]:
    """Query string as stored in integration logs (real token is sent on the wire only)."""
    return build_orange_reschedule_query_log(token)


def build_cancel_internal_metadata(*, request_id: str, token: str | None) -> dict[str, Any]:
    internal: dict[str, Any] = {"request_id": request_id}
    suffix = token_suffix(token)
    if suffix:
        internal["token_suffix"] = suffix
    return internal