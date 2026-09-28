"""Pick the diagnostic package for one participant on an engagement.

Unisex and B2C engagements store only diagnostic_package_id.
Split camps store male and female packages and leave the unisex column null.
"""

from __future__ import annotations

from typing import Any

from core.exceptions import AppError


def healthians_gender_code(raw: str | None) -> str | None:
    """Map free-text user gender to Healthians M or F. Unknown values return None."""
    value = (raw or "").strip()
    if not value:
        return None
    if value in {"1", "M", "m"}:
        return "M"
    if value in {"2", "F", "f"}:
        return "F"
    lowered = value.lower()
    if lowered.startswith("m"):
        return "M"
    if lowered.startswith("f"):
        return "F"
    return None


def is_split_diagnostic_engagement(engagement: Any) -> bool:
    return (
        getattr(engagement, "diagnostic_package_id_male", None) is not None
        or getattr(engagement, "diagnostic_package_id_female", None) is not None
    )


def engagement_has_diagnostic_package(engagement: Any) -> bool:
    return (
        getattr(engagement, "diagnostic_package_id", None) is not None
        or is_split_diagnostic_engagement(engagement)
    )


def resolve_diagnostic_package_id(engagement: Any, *, user_gender: str | None) -> int:
    """Return the package id to book or score for this participant.

    Split camps require a male or female gender. There is no fallback to the
    unisex column and no default to male.
    """
    if is_split_diagnostic_engagement(engagement):
        code = healthians_gender_code(user_gender)
        if code == "F" and engagement.diagnostic_package_id_female is not None:
            return int(engagement.diagnostic_package_id_female)
        if code == "M" and engagement.diagnostic_package_id_male is not None:
            return int(engagement.diagnostic_package_id_male)
        raise AppError(
            status_code=422,
            error_code="PARTICIPANT_GENDER_REQUIRED",
            message="Participant gender must be male or female to choose a blood package for this engagement",
        )
    if engagement.diagnostic_package_id is None:
        raise AppError(
            status_code=422,
            error_code="INVALID_STATE",
            message="Engagement has no diagnostic package configured",
        )
    return int(engagement.diagnostic_package_id)
