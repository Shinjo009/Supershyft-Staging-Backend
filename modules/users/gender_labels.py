"""Normalize user / questionnaire gender values to ``male`` or ``female``."""

from __future__ import annotations

import enum

from db.column_types import UserGender


def normalize_gender_label(raw: object | None) -> str | None:
    """Map DB enums, MetSights codes, and labels to ``male`` or ``female``."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, enum.Enum):
        raw = raw.value

    if isinstance(raw, (int, float)):
        code = int(raw)
        if code == 1:
            return "male"
        if code == 2:
            return "female"
        return None

    text = str(raw).strip()
    if not text:
        return None
    lowered = text.lower()

    for member in UserGender:
        if lowered == member.value.lower() or lowered == member.name.lower():
            return "male" if member.name.startswith("male") else "female"
        dotted = f".{member.name.lower()}"
        if lowered.endswith(dotted) or lowered.endswith(f"usergender{dotted}"):
            return "male" if member.name.startswith("male") else "female"

    if lowered in {"m", "man", "male", "1"}:
        return "male"
    if lowered in {"f", "woman", "female", "2"}:
        return "female"
    return None
