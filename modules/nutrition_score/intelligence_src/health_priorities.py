"""Isolated health-priority option maps.

Copied exactly from SuperShyft ``db.seed.questionnaire_field_config``.
Do not invent or "correct" these values — they are part of scoring/context
resolution for ``health_priorities``.
"""

from __future__ import annotations

HEALTH_PRIORITIES_OPTION_VALUES: frozenset[str] = frozenset({
    "0",
    "1",
    "2",
    "3",
    "4",
    "5",
})

HEALTH_PRIORITIES_LABEL_TO_VALUE: dict[str, str] = {
    "weight loss": "0",
    "building muscle mass": "1",
    "improving metabolic health": "2",
    "increasing energy levels": "3",
    "increasing strength": "4",
    "improving physical endurance": "5",
}
