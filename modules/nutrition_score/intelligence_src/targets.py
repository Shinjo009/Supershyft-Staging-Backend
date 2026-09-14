"""Nutrition Target Generator (Phase 11).

Produces goal-aware carbohydrate / protein / fat / fibre / water TARGETS
from configuration + user context (weight, gender, activity, goals).

TARGETS ≠ measured intake. This module must never feed Nutrition Score.
Does not estimate carbohydrate/protein/fat/fibre intake.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Literal

from modules.nutrition_score.intelligence_src.config_loader import (
    MacroTargetSet,
    NutritionEngineConfig,
    TargetDefinition,
    TargetGeneratorConfig,
    load_nutrition_engine_config,
)
from modules.nutrition_score.intelligence_src.models import (
    CombinedNutritionProfile,
    GoalId,
    NormalizedAnswers,
    NutritionTargets,
    ScaleValue,
    TargetRange,
)

ActivityBand = Literal["low", "moderate", "high"]


def generate_nutrition_targets(
    combined_profile: CombinedNutritionProfile,
    answers: NormalizedAnswers,
    *,
    config: NutritionEngineConfig | None = None,
) -> NutritionTargets:
    """Generate structured NutritionTargets for the resolved goal profile.

    Uses CombinedNutritionProfile (Phase 6) plus user context. Does not
    recalculate behaviour scores or modify Nutrition Score inputs.
    """
    engine_config = config or load_nutrition_engine_config()
    tg = engine_config.target_generator
    if tg is None:
        raise ValueError("targets.yaml: target generator configuration is missing")

    activity_band = derive_activity_band(answers)
    weight_kg = _weight_kg(answers.weight)
    gender = answers.gender

    base = _resolve_base_targets(combined_profile, engine_config, tg)
    protein_g_per_kg = base.protein_g_per_kg
    carbohydrate_g_per_kg = _apply_activity_to_carbohydrate(
        combined_profile,
        base.carbohydrate_g_per_kg,
        activity_band,
        engine_config,
    )
    fibre_priority = base.fibre_priority
    hydration_priority = base.hydration_priority or "standard"
    energy_concept = base.energy_concept

    macros = _resolve_macro_targets(combined_profile.goals, tg)
    water = _resolve_water_target(
        hydration_priority=hydration_priority,
        gender=gender,
        activity_band=activity_band,
        tg=tg,
    )

    protein_g = _scale_by_weight(protein_g_per_kg, weight_kg, unit="g_day")
    carbohydrate_g = _scale_by_weight(carbohydrate_g_per_kg, weight_kg, unit="g_day")

    notes = list(base.notes)
    notes.append(f"activity_band:{activity_band}")
    if weight_kg is None:
        notes.append("weight_unavailable:absolute_g_targets_omitted")
    if not combined_profile.goals:
        notes.append("zero_goal_targets")

    return NutritionTargets(
        protein_g_per_kg=_copy_range(protein_g_per_kg),
        carbohydrate_g_per_kg=_copy_range(carbohydrate_g_per_kg),
        fibre_priority=fibre_priority,
        hydration_priority=hydration_priority,
        energy_concept=energy_concept,
        carbohydrate_percent=_copy_range(macros.carbohydrate_percent),
        protein_percent=_copy_range(macros.protein_percent),
        fat_percent=_copy_range(macros.fat_percent),
        fibre_g=_copy_range(macros.fibre_g),
        water_l=_copy_range(water),
        protein_g=_copy_range(protein_g),
        carbohydrate_g=_copy_range(carbohydrate_g),
        activity_band=activity_band,
        notes=tuple(notes),
    )


def derive_activity_band(answers: NormalizedAnswers) -> ActivityBand:
    """Map questionnaire exercise fields → low/moderate/high TARGET band.

    Used only for target modification (e.g. endurance carbohydrate, water uplift).
    Must never alter Nutrition Score.
    """
    freq = str(answers.exercise_frequency_week).strip() if answers.exercise_frequency_week else None
    level = str(answers.exercise_level).strip() if answers.exercise_level else None

    # High training load.
    if freq in {"3", "4"} or level == "2":
        return "high"
    # Sedentary / rarely.
    if freq in {"0", "1"} and (level is None or level == "0"):
        return "low"
    if freq is None and level is None:
        return "low"
    return "moderate"


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _resolve_base_targets(
    combined: CombinedNutritionProfile,
    config: NutritionEngineConfig,
    tg: TargetGeneratorConfig,
) -> NutritionTargets:
    if combined.merged_targets is not None and combined.goals:
        # Two-goal path already merged g/kg + priorities in Phase 6.
        return combined.merged_targets

    if len(combined.goals) == 1:
        goal_id = combined.goals[0]
        profile = config.goals[goal_id]
        return _targets_from_keys(profile.base_target_keys, config)

    # Zero goals — configured baseline keys (not inventing a second goal).
    return _targets_from_keys(tg.zero_goal_target_keys, config)


def _targets_from_keys(
    keys: tuple[str, ...],
    config: NutritionEngineConfig,
) -> NutritionTargets:
    protein_range: TargetRange | None = None
    carb_range: TargetRange | None = None
    fibre_priority: str | None = None
    hydration_priority: str | None = None
    energy_concept: str | None = None
    notes: list[str] = []

    for key in keys:
        definition = config.targets.get(key)
        if definition is None:
            raise ValueError(f"Unknown target key {key!r}")
        notes.extend(definition.notes)
        if definition.kind == "protein_g_per_kg":
            protein_range = definition.range
        elif definition.kind == "carbohydrate_g_per_kg":
            carb_range = definition.range
        elif definition.kind == "fibre_priority":
            fibre_priority = definition.priority
        elif definition.kind == "hydration_priority":
            hydration_priority = definition.priority
        elif definition.kind == "energy_concept":
            energy_concept = definition.concept

    return NutritionTargets(
        protein_g_per_kg=_copy_range(protein_range),
        carbohydrate_g_per_kg=_copy_range(carb_range),
        fibre_priority=fibre_priority,
        hydration_priority=hydration_priority,
        energy_concept=energy_concept,
        notes=tuple(notes),
    )


def _apply_activity_to_carbohydrate(
    combined: CombinedNutritionProfile,
    carb_range: TargetRange | None,
    activity_band: ActivityBand,
    config: NutritionEngineConfig,
) -> TargetRange | None:
    """If endurance activity-dependent carb target is active, select band."""
    # Prefer explicit activity-dependent definition when present in selected keys.
    for key in combined.target_keys:
        definition = config.targets.get(key)
        if definition is None:
            continue
        if definition.kind != "carbohydrate_g_per_kg":
            continue
        if definition.range and definition.range.mode == "activity_dependent":
            return _band_or_default(definition, activity_band)

    # Single-goal endurance: target_keys are base keys; check mode on resolved range.
    if carb_range is not None and carb_range.mode == "activity_dependent":
        # Look up the endurance definition from config.
        endurance_def = config.targets.get("carbohydrate_endurance_activity_dependent")
        if endurance_def is not None:
            return _band_or_default(endurance_def, activity_band)
    return _copy_range(carb_range)


def _band_or_default(definition: TargetDefinition, activity_band: ActivityBand) -> TargetRange | None:
    band = definition.activity_bands.get(activity_band)
    if band is not None:
        return TargetRange(
            low=band.low,
            high=band.high,
            unit=band.unit or (definition.range.unit if definition.range else None),
            mode="activity_dependent",
        )
    return _copy_range(definition.range)


def _resolve_macro_targets(
    goals: tuple[GoalId, ...],
    tg: TargetGeneratorConfig,
) -> MacroTargetSet:
    if not goals:
        return tg.general_macro_targets
    if len(goals) == 1:
        return tg.goal_macro_targets[goals[0]]

    left = tg.goal_macro_targets[goals[0]]
    right = tg.goal_macro_targets[goals[1]]
    strategies = tg.macro_combination
    return MacroTargetSet(
        carbohydrate_percent=_merge_ranges(
            left.carbohydrate_percent,
            right.carbohydrate_percent,
            strategies.get("carbohydrate_percent", "overlap_or_widen"),
        ),
        fat_percent=_merge_ranges(
            left.fat_percent,
            right.fat_percent,
            strategies.get("fat_percent", "overlap_or_widen"),
        ),
        protein_percent=_merge_ranges(
            left.protein_percent,
            right.protein_percent,
            strategies.get("protein_percent", "overlap_or_widen"),
        ),
        fibre_g=_merge_ranges(
            left.fibre_g,
            right.fibre_g,
            strategies.get("fibre_g", "prefer_higher"),
        ),
    )


def _merge_ranges(
    a: TargetRange | None,
    b: TargetRange | None,
    strategy: str,
) -> TargetRange | None:
    if a is None:
        return _copy_range(b)
    if b is None:
        return _copy_range(a)

    if strategy == "prefer_higher":
        lows = [x for x in (a.low, b.low) if x is not None]
        highs = [x for x in (a.high, b.high) if x is not None]
        return TargetRange(
            low=max(lows) if lows else None,
            high=max(highs) if highs else None,
            unit=a.unit or b.unit,
            mode=a.mode or b.mode,
        )

    # Default: overlap_or_widen
    if a.low is None or a.high is None or b.low is None or b.high is None:
        # Incomplete numeric ranges → widen over available bounds.
        lows = [x for x in (a.low, b.low) if x is not None]
        highs = [x for x in (a.high, b.high) if x is not None]
        return TargetRange(
            low=min(lows) if lows else None,
            high=max(highs) if highs else None,
            unit=a.unit or b.unit,
            mode=a.mode or b.mode,
        )

    overlap_low = max(a.low, b.low)
    overlap_high = min(a.high, b.high)
    if overlap_low <= overlap_high:
        return TargetRange(
            low=overlap_low,
            high=overlap_high,
            unit=a.unit or b.unit,
            mode=a.mode or b.mode,
        )
    return TargetRange(
        low=min(a.low, b.low),
        high=max(a.high, b.high),
        unit=a.unit or b.unit,
        mode=a.mode or b.mode,
    )


def _resolve_water_target(
    *,
    hydration_priority: str,
    gender: str | None,
    activity_band: ActivityBand,
    tg: TargetGeneratorConfig,
) -> TargetRange | None:
    by_priority = tg.water_targets.get(hydration_priority) or tg.water_targets.get("standard")
    if not by_priority:
        return None

    gender_key = None
    if gender in {"male", "female"}:
        gender_key = gender
    base = by_priority.get(gender_key) if gender_key else None
    if base is None:
        base = by_priority.get("default")
    if base is None:
        return None

    uplift = float(tg.activity_water_uplift_l.get(activity_band, 0.0))
    low = base.low + uplift if base.low is not None else None
    high = base.high + uplift if base.high is not None else None
    return TargetRange(low=low, high=high, unit=base.unit or "L_day", mode=base.mode)


def _weight_kg(weight: ScaleValue | None) -> float | None:
    if weight is None or weight.value is None:
        return None
    try:
        value = float(weight.value)
    except (TypeError, ValueError):
        return None
    unit = (weight.unit or "kg").strip().lower()
    if unit in {"lb", "lbs", "1"}:
        return value * 0.45359237
    return value


def _scale_by_weight(
    per_kg: TargetRange | None,
    weight_kg: float | None,
    *,
    unit: str,
) -> TargetRange | None:
    if per_kg is None or weight_kg is None:
        return None
    if per_kg.low is None and per_kg.high is None:
        return None
    return TargetRange(
        low=(per_kg.low * weight_kg) if per_kg.low is not None else None,
        high=(per_kg.high * weight_kg) if per_kg.high is not None else None,
        unit=unit,
        mode=per_kg.mode,
    )


def _copy_range(value: TargetRange | None) -> TargetRange | None:
    if value is None:
        return None
    return deepcopy(value)
