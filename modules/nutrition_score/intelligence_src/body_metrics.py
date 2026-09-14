"""Configured reference body metrics.

Ideal/reference values are read exclusively from ``targets.yaml`` and never
feed back into Nutrition Score. Current BMR belongs to the backend/Metsights
integration and is not calculated by this engine.
"""

from __future__ import annotations

from modules.nutrition_score.intelligence_src.config_loader import (
    NutritionEngineConfig,
    load_nutrition_engine_config,
)
from modules.nutrition_score.intelligence_src.models import (
    CombinedNutritionProfile,
    IdealBodyMetrics,
    NormalizedAnswers,
    TargetRange,
)


def resolve_ideal_bmr(
    age: int | None,
    gender: str | None,
    *,
    config: NutritionEngineConfig | None = None,
) -> TargetRange | None:
    """Resolve the YAML product reference range by age and gender."""
    if age is None or age < 18 or gender not in {"male", "female"}:
        return None
    if age <= 29:
        age_band = "age_18_29"
    elif age <= 59:
        age_band = "age_30_59"
    else:
        age_band = "age_60_plus"

    engine = config or load_nutrition_engine_config()
    metric_config = engine.body_metric_targets
    if metric_config is None:
        return None
    return _copy_range(metric_config.bmr_reference_ranges.get(age_band, {}).get(gender))


def resolve_ideal_body_metrics(
    answers: NormalizedAnswers,
    combined_profile: CombinedNutritionProfile,
    *,
    config: NutritionEngineConfig | None = None,
) -> IdealBodyMetrics:
    """Resolve configured BMR, waist, and body-fat references.

    BMR is deliberately age/gender-only. Waist and body fat use any configured
    goal overrides, merged deterministically, then fall back to general values.
    """
    engine = config or load_nutrition_engine_config()
    metric_config = engine.body_metric_targets
    if metric_config is None:
        return IdealBodyMetrics(waist_input_unit=answers.waist_input_unit)

    return IdealBodyMetrics(
        ideal_bmr=resolve_ideal_bmr(answers.age, answers.gender, config=engine),
        ideal_waist_cm=_resolve_goal_aware_metric(
            answers.gender,
            combined_profile.goals,
            metric_config.waist_general,
            metric_config.waist_goal_overrides,
        ),
        waist_input_unit=answers.waist_input_unit,
        ideal_body_fat_percent=_resolve_goal_aware_metric(
            answers.gender,
            combined_profile.goals,
            metric_config.body_fat_general,
            metric_config.body_fat_goal_overrides,
        ),
    )


def _resolve_goal_aware_metric(
    gender: str | None,
    goals: tuple[str, ...],
    general: dict[str, TargetRange],
    overrides: dict[str, dict[str, TargetRange]],
) -> TargetRange | None:
    if gender not in {"male", "female"}:
        return None

    selected = [
        by_gender[gender]
        for goal in goals
        if (by_gender := overrides.get(goal)) is not None and gender in by_gender
    ]
    if not selected:
        return _copy_range(general.get(gender))

    merged = selected[0]
    for target in selected[1:]:
        merged = _merge_ranges(merged, target)
    return _copy_range(merged)


def _merge_ranges(left: TargetRange, right: TargetRange) -> TargetRange:
    """Use overlap when possible, otherwise deterministic widened bounds."""
    if (
        left.low is not None
        and left.high is not None
        and right.low is not None
        and right.high is not None
    ):
        overlap_low = max(left.low, right.low)
        overlap_high = min(left.high, right.high)
        if overlap_low <= overlap_high:
            return TargetRange(
                low=overlap_low,
                high=overlap_high,
                unit=left.unit or right.unit,
            )
    lows = [value for value in (left.low, right.low) if value is not None]
    highs = [value for value in (left.high, right.high) if value is not None]
    return TargetRange(
        low=min(lows) if lows else None,
        high=max(highs) if highs else None,
        unit=left.unit or right.unit,
    )


def _copy_range(value: TargetRange | None) -> TargetRange | None:
    if value is None:
        return None
    return TargetRange(
        low=value.low,
        high=value.high,
        unit=value.unit,
        mode=value.mode,
    )
