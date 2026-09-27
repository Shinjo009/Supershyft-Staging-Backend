"""Defaults for load_prev_assessment_questionnaires category allow-list."""

from __future__ import annotations

DEFAULT_LOAD_PREV_QUESTIONNAIRE_CATEGORY_KEYS: frozenset[str] = frozenset(
    {
        "physical-measurement",
        "diet-lifestyle-parameters",
        "anthropometry",
        "nutrition_log",
        "family_history",
    }
)


def resolve_load_prev_category_keys(
    configured: list[str] | None,
) -> frozenset[str]:
    """Return allow-list for copying prior questionnaire answers."""
    if configured:
        cleaned = {str(k).strip() for k in configured if str(k).strip()}
        if cleaned:
            return frozenset(cleaned)
    return DEFAULT_LOAD_PREV_QUESTIONNAIRE_CATEGORY_KEYS
