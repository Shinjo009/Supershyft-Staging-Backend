"""Category rating keys shown on the participant feedback form by engagement type."""

from __future__ import annotations

from modules.engagements.enums import EngagementKind

_CATEGORY_BLOOD = "blood_collection"
_CATEGORY_BIO_AI = "bio_ai_reports"
_CATEGORY_CONSULTATION = "consultations"

_ALLOWED_CATEGORY_KEYS = frozenset({_CATEGORY_BLOOD, _CATEGORY_BIO_AI, _CATEGORY_CONSULTATION})

_TYPE_GATES: dict[str, dict[str, bool]] = {
    EngagementKind.bio_ai.value: {
        "needsAssessment": True,
        "needsBloodCollection": True,
    },
    EngagementKind.blood_test.value: {
        "needsBloodCollection": True,
    },
    EngagementKind.consultation.value: {
        "needsConsultation": True,
    },
    EngagementKind.blood_test_with_consultation.value: {
        "needsBloodCollection": True,
        "needsConsultation": True,
    },
    EngagementKind.bio_ai_with_consultation.value: {
        "needsAssessment": True,
        "needsBloodCollection": True,
        "needsConsultation": True,
    },
}


def category_keys_for_engagement_type_code(type_code: str | None) -> list[str]:
    code = (type_code or "").strip().lower()
    gates = _TYPE_GATES.get(code, {})
    keys: list[str] = []
    if gates.get("needsBloodCollection"):
        keys.append(_CATEGORY_BLOOD)
    if gates.get("needsAssessment"):
        keys.append(_CATEGORY_BIO_AI)
    if gates.get("needsConsultation"):
        keys.append(_CATEGORY_CONSULTATION)
    return keys


def validate_category_ratings(
    category_ratings: dict[str, object],
    *,
    allowed_keys: list[str],
) -> dict[str, int]:
    allowed = set(allowed_keys)
    if not isinstance(category_ratings, dict):
        raise ValueError("category_ratings must be an object")
    out: dict[str, int] = {}
    for key, value in category_ratings.items():
        if key not in _ALLOWED_CATEGORY_KEYS:
            raise ValueError(f"Unknown category key: {key}")
        if key not in allowed:
            raise ValueError(f"Category not applicable for this engagement: {key}")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"Invalid rating for {key}")
        if value < 1 or value > 5:
            raise ValueError(f"Rating for {key} must be between 1 and 5")
        out[key] = value
    return out
