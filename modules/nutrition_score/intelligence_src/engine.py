"""Public Nutrition Intelligence Engine entry points.

Orchestrates questionnaire → NormalizedAnswers → NutritionUserResult, and
serializes results into the Health Span Index / ReportsService contract.

Does not change scoring, macro, fibre, water, or target methodologies.
"""

from __future__ import annotations

from typing import Any

from modules.nutrition_score.intelligence_src.config_loader import (
    NutritionEngineConfig,
    load_nutrition_engine_config,
)
from modules.nutrition_score.intelligence_src.models import (
    EstimatedMacroPercent,
    IdealBodyMetrics,
    NormalizedAnswers,
    NutritionTargets,
    NutritionUserResult,
    TargetRange,
)
from modules.nutrition_score.intelligence_src.questionnaire import normalize_questionnaire_lookup
from modules.nutrition_score.intelligence_src.result import compose_user_result, format_user_result
from modules.nutrition_score.intelligence_src.scoring import display_nutrition_score

# Re-export for callers that want a single engine import surface.
__all__ = [
    "calculate_nutrition_intelligence",
    "format_user_result",
    "run_nutrition_intelligence_from_lookup",
    "serialize_health_span_nutrition",
]


def calculate_nutrition_intelligence(
    answers: NormalizedAnswers,
    *,
    config: NutritionEngineConfig | None = None,
) -> NutritionUserResult:
    """Run the Nutrition Intelligence Engine on normalized answers."""
    return compose_user_result(answers, config=config)


def run_nutrition_intelligence_from_lookup(
    lookup: dict[str, Any],
    *,
    user_gender: str | None = None,
    option_reverse_map: dict[str, dict[str, str]] | None = None,
    config: NutritionEngineConfig | None = None,
) -> NutritionUserResult:
    """Normalize a questionnaire lookup (stable option codes) then run the engine.

    Frontend / API must send backend option_value codes, not display indexes.
    """
    answers = normalize_questionnaire_lookup(
        lookup,
        user_gender=user_gender,
        option_reverse_map=option_reverse_map,
    )
    return calculate_nutrition_intelligence(answers, config=config)


def serialize_health_span_nutrition(result: NutritionUserResult) -> dict[str, Any]:
    """Map NutritionUserResult → Health Span Index nutrition response dict.

    Preserves the existing frontend contract keys:
    nutrition_score, carbs, fats, protein, fibre, water.
    """
    current = result.current_nutrition
    ideal = result.goal_based_ideal
    ideal_body = result.ideal_body_metrics or IdealBodyMetrics()

    payload: dict[str, Any] = {
        # Public contract is a whole number. Internal Final = 0.70*Q + 0.30*A
        # stays on nutrition_score_raw at full precision.
        "nutrition_score": display_nutrition_score(
            result.nutrition_score_raw
            if result.nutrition_score_raw is not None
            else result.nutrition_score
        ),
        "risk_band": result.risk_band,
        "carbs": _nutrient_percent(
            current.estimated_carbohydrate_percent,
            ideal.carbohydrate_percent if ideal is not None else None,
        ),
        "fats": _nutrient_percent(
            current.estimated_fat_percent,
            ideal.fat_percent if ideal is not None else None,
        ),
        "protein": _nutrient_percent(
            current.estimated_protein_percent,
            ideal.protein_percent if ideal is not None else None,
        ),
        "fibre": _nutrient_grams(
            current.fibre.low_g if current.fibre.available else None,
            current.fibre.high_g if current.fibre.available else None,
            ideal.fibre_g if ideal is not None else None,
        ),
        "water": _water_detail(current, ideal),
        "ideal_bmr": _target_metric(ideal_body.ideal_bmr),
        "ideal_waist": _waist_target_metric(
            ideal_body.ideal_waist_cm,
            ideal_body.waist_input_unit,
        ),
        "ideal_body_fat": _target_metric(
            ideal_body.ideal_body_fat_percent,
            unit_override="%",
        ),
        "disclaimer": result.disclaimer,
        "goals": list(result.goals),
    }
    return payload


def _target_metric(
    target: TargetRange | None,
    *,
    unit_override: str | None = None,
) -> dict[str, Any] | None:
    if target is None:
        return None
    return {
        "low": _json_number(target.low),
        "high": _json_number(target.high),
        "unit": unit_override or target.unit,
    }


def _waist_target_metric(
    target: TargetRange | None,
    input_unit: str | None,
) -> dict[str, Any] | None:
    """Return canonical cm plus human-readable inches without changing biology."""
    if target is None:
        return None
    cm_low = _rounded_measurement(target.low)
    cm_high = _rounded_measurement(target.high)
    in_low = _rounded_measurement(
        float(target.low) / 2.54 if target.low is not None else None
    )
    in_high = _rounded_measurement(
        float(target.high) / 2.54 if target.high is not None else None
    )
    return {
        # Preserve the existing contract for current consumers.
        "low": cm_low,
        "high": cm_high,
        "unit": "cm",
        "cm": {"low": cm_low, "high": cm_high},
        "in": {"low": in_low, "high": in_high},
        "input_unit": input_unit,
    }


def _rounded_measurement(value: float | int | None) -> float | int | None:
    if value is None:
        return None
    return _json_number(round(float(value), 1))


def _json_number(value: float | int | None) -> float | int | None:
    if value is None:
        return None
    numeric = float(value)
    return int(numeric) if numeric.is_integer() else numeric


def _nutrient_percent(
    estimated: EstimatedMacroPercent | None,
    ideal: TargetRange | None,
) -> dict[str, Any] | None:
    if estimated is None and ideal is None:
        return None
    estimated_low = float(estimated.lower) if estimated is not None else None
    estimated_high = float(estimated.upper) if estimated is not None else None
    ideal_low = float(ideal.low) if ideal is not None and ideal.low is not None else None
    ideal_high = float(ideal.high) if ideal is not None and ideal.high is not None else None
    return {
        "estimated_low": estimated_low,
        "estimated_high": estimated_high,
        "ideal_low": ideal_low,
        "ideal_high": ideal_high,
        "status": _range_status(estimated_low, estimated_high, ideal_low, ideal_high),
    }


def _nutrient_grams(
    estimated_low: float | None,
    estimated_high: float | None,
    ideal: TargetRange | None,
) -> dict[str, Any] | None:
    if estimated_low is None and estimated_high is None and ideal is None:
        return None
    current_low = float(estimated_low) if estimated_low is not None else None
    current_high = float(estimated_high) if estimated_high is not None else None
    ideal_low = float(ideal.low) if ideal is not None and ideal.low is not None else None
    ideal_high = float(ideal.high) if ideal is not None and ideal.high is not None else None
    return {
        "estimated_low": current_low,
        "estimated_high": current_high,
        "ideal_low": ideal_low,
        "ideal_high": ideal_high,
        "status": _range_status(current_low, current_high, ideal_low, ideal_high),
    }


def _water_detail(
    current,
    ideal: NutritionTargets | None,
) -> dict[str, Any] | None:
    water = current.water
    ideal_water = ideal.water_l if ideal is not None else None
    if not water.available and ideal_water is None:
        return None

    low = float(water.low_l) if water.available and water.low_l is not None else None
    high = float(water.high_l) if water.available and water.high_l is not None else None
    midpoint = None
    if low is not None and high is not None:
        midpoint = (low + high) / 2.0
    elif low is not None:
        midpoint = low
    elif high is not None:
        midpoint = high
    if midpoint is not None:
        midpoint = round(midpoint, 2)

    ideal_low = (
        float(ideal_water.low)
        if ideal_water is not None and ideal_water.low is not None
        else None
    )
    ideal_high = (
        float(ideal_water.high)
        if ideal_water is not None and ideal_water.high is not None
        else None
    )

    return {
        "estimated_litres": midpoint,
        "ideal_low_litres": ideal_low,
        "ideal_high_litres": ideal_high,
        "status": _range_status(midpoint, midpoint, ideal_low, ideal_high),
    }


def _range_status(
    estimated_low: float | None,
    estimated_high: float | None,
    ideal_low: float | None,
    ideal_high: float | None,
) -> str | None:
    """Classify an estimate against an ideal range without changing estimates."""
    if None in (estimated_low, estimated_high, ideal_low, ideal_high):
        return None
    if estimated_low > ideal_high:
        return "above_ideal"
    if estimated_high < ideal_low:
        return "below_ideal"
    return "within_ideal"
