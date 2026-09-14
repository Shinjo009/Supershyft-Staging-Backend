"""Behaviour Indicator Engine for the Nutrition Intelligence Engine.

Converts NormalizedAnswers into per-indicator behavioural scores (0–100).

Does not calculate nutrition_score, general quality, goal alignment, targets,
or measured intake. Goal selection and activity must not alter raw scores.
"""

from __future__ import annotations

from typing import Any

from modules.nutrition_score.intelligence_src.config_loader import (
    NutritionEngineConfig,
    load_nutrition_engine_config,
)
from modules.nutrition_score.intelligence_src.models import (
    IndicatorDefinition,
    IndicatorScore,
    NormalizedAnswers,
)

# diet_preference option codes → which configured protein-supporting food-group
# codes are treated as *applicable evidence* for that diet context.
# This is CONTEXT for interpreting food_groups — never a direct score delta
# for being vegetarian / Jain / etc.
#
# Assumption (documented): codes outside the applicable set are ignored in both
# numerator and denominator so users are not penalised for not selecting
# food groups atypical for their diet. Codes come from indicators.yaml
# protein_supporting_group_codes; this map only filters that list.
_DIET_APPLICABLE_PROTEIN_CODES: dict[str, frozenset[str]] = {
    "0": frozenset({"1", "2", "5"}),  # Vegetarian: pulses, dairy, nuts
    "5": frozenset({"1", "2", "5"}),  # Jain: same plant/dairy evidence set
    "2": frozenset({"1", "2", "5", "6"}),  # Eggetarian: + eggs
    "3": frozenset({"1", "2", "5", "6", "7"}),  # Pescatarian: + eggs/fish-meat code
    "4": frozenset({"1", "2", "5", "6", "7"}),  # Flexitarian: full set
    "1": frozenset({"1", "2", "5", "6", "7"}),  # Non-vegetarian: full set
}


def evaluate_behaviour_indicators(
    answers: NormalizedAnswers,
    *,
    config: NutritionEngineConfig | None = None,
) -> dict[str, IndicatorScore]:
    """Evaluate all configured indicators from normalized questionnaire answers.

    Missing required source fields → ``score=None`` (not automatic 0).
    Present-but-empty multi-selects (e.g. food_groups=()) can score 0.
    """
    engine_config = config or load_nutrition_engine_config()
    results: dict[str, IndicatorScore] = {}
    for indicator_id, definition in engine_config.indicators.items():
        score = _score_indicator(definition, answers)
        results[indicator_id] = IndicatorScore(
            indicator_id=indicator_id,
            score=score,
            source_fields=definition.source_fields,
            is_behavioural_proxy=definition.is_behavioural_proxy,
            general_quality_priority=definition.general_quality_priority,
            goal_relevance=dict(definition.goal_relevance),
        )
    return results


def _score_indicator(definition: IndicatorDefinition, answers: NormalizedAnswers) -> float | None:
    if definition.id == "food_diversity":
        return _score_food_diversity(definition, answers)
    if definition.id == "protein_supporting_foods":
        return _score_protein_supporting_foods(definition, answers)
    if definition.ordinal_scores:
        return _score_ordinal(definition, answers)
    return None


def _answer_value(answers: NormalizedAnswers, field_name: str) -> Any:
    if not hasattr(answers, field_name):
        return None
    return getattr(answers, field_name)


def _score_ordinal(definition: IndicatorDefinition, answers: NormalizedAnswers) -> float | None:
    # Primary questionnaire field is the first source field for ordinal indicators.
    if not definition.source_fields:
        return None
    field_name = definition.source_fields[0]
    raw = _answer_value(answers, field_name)
    if raw is None:
        return None
    code = str(raw).strip()
    if not code:
        return None
    if code not in definition.ordinal_scores:
        # Invalid / unknown code → missing, not fabricated poor behaviour.
        return None
    value = float(definition.ordinal_scores[code])
    return _clamp_0_100(value)


def _score_food_diversity(definition: IndicatorDefinition, answers: NormalizedAnswers) -> float | None:
    if answers.food_groups is None:
        return None
    quality_codes = definition.quality_group_codes
    if not quality_codes:
        return None
    selected = {str(code) for code in answers.food_groups}
    matched = sum(1 for code in quality_codes if code in selected)
    return _clamp_0_100(100.0 * matched / len(quality_codes))


def _score_protein_supporting_foods(
    definition: IndicatorDefinition,
    answers: NormalizedAnswers,
) -> float | None:
    if answers.food_groups is None:
        return None
    configured = definition.protein_supporting_group_codes
    if not configured:
        return None

    applicable = _applicable_protein_codes(configured, answers.diet_preference)
    if not applicable:
        return None

    selected = {str(code) for code in answers.food_groups}
    matched = sum(1 for code in applicable if code in selected)
    return _clamp_0_100(100.0 * matched / len(applicable))


def _applicable_protein_codes(
    configured: tuple[str, ...],
    diet_preference: str | None,
) -> tuple[str, ...]:
    """Filter configured protein-supporting codes by diet context.

    If diet_preference is missing/unknown, all configured codes remain applicable
    (no invented diet penalty).
    """
    if diet_preference is None:
        return configured
    diet = str(diet_preference).strip()
    allowed = _DIET_APPLICABLE_PROTEIN_CODES.get(diet)
    if allowed is None:
        return configured
    return tuple(code for code in configured if code in allowed)


def _clamp_0_100(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 100:
        return 100.0
    return float(value)
