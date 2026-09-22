"""Estimated current nutrition pattern (Phase 12 + C/P/F distribution).

Questionnaire-supported consumption estimates only.
Never feeds Nutrition Score, General Quality, or Goal Alignment.
C/P/F percentages are questionnaire-based estimated ranges, not measurements.
"""

from __future__ import annotations

from typing import Any

from modules.nutrition_score.intelligence_src.config_loader import (
    NutritionEngineConfig,
    load_nutrition_engine_config,
)
from modules.nutrition_score.intelligence_src.models import (
    CarbohydratePattern,
    ConfidenceLevel,
    EstimatedMacroPercent,
    EstimatedNutritionIntake,
    FatPattern,
    FibreEstimate,
    NormalizedAnswers,
    ProteinPattern,
    WaterEstimate,
)


def estimate_current_nutrition(
    answers: NormalizedAnswers,
    *,
    config: NutritionEngineConfig | None = None,
) -> EstimatedNutritionIntake:
    """Estimate current nutrition pattern from normalized questionnaire answers.

    Ignores goals, activity, weight, and height.
    """
    engine = config or load_nutrition_engine_config()
    spec = engine.consumption or {}
    carbohydrate = _estimate_carbohydrate(
        answers, spec.get("carbohydrate") or {}, spec.get("confidence") or {}
    )
    protein = _estimate_protein(
        answers, spec.get("protein") or {}, spec.get("confidence") or {}
    )
    fat = _estimate_fat(answers, spec.get("fat") or {}, spec.get("confidence") or {})
    carb_pct, protein_pct, fat_pct = _estimate_macro_distribution(
        answers,
        spec.get("macro_distribution") or {},
        spec.get("protein") or {},
        carbohydrate_pattern=carbohydrate.pattern,
        protein_pattern=protein.adequacy_tier,
        fat_pattern=fat.tendency,
    )
    return EstimatedNutritionIntake(
        water=_estimate_water(answers, spec.get("water") or {}, spec.get("confidence") or {}),
        fibre=_estimate_fibre(answers, spec.get("fibre") or {}, spec.get("confidence") or {}),
        carbohydrate=carbohydrate,
        protein=protein,
        fat=fat,
        estimated_carbohydrate_percent=carb_pct,
        estimated_protein_percent=protein_pct,
        estimated_fat_percent=fat_pct,
    )


# ---------------------------------------------------------------------------
# Water
# ---------------------------------------------------------------------------


def _estimate_water(
    answers: NormalizedAnswers,
    water_cfg: dict[str, Any],
    confidence_cfg: dict[str, Any],
) -> WaterEstimate:
    note = str(water_cfg.get("note") or "")
    code = answers.water_intake_frequency
    water_conf = confidence_cfg.get("water") or {}
    if code is None:
        return WaterEstimate(
            low_l=None,
            high_l=None,
            confidence=_as_confidence(water_conf.get("missing", "INSUFFICIENT")),
            available=False,
            note=note,
        )

    mappings = water_cfg.get("frequency_mappings") or {}
    band = mappings.get(str(code).strip())
    if not isinstance(band, dict):
        return WaterEstimate(
            low_l=None,
            high_l=None,
            confidence=_as_confidence(water_conf.get("missing", "INSUFFICIENT")),
            available=False,
            note=note,
        )

    low = float(band["low"])
    high = float(band["high"])
    low, high = _add_caffeine_fluid(answers, water_cfg, low, high)
    return WaterEstimate(
        low_l=low,
        high_l=high,
        confidence=_as_confidence(water_conf.get("present", "HIGH")),
        available=True,
        note=note,
    )


def _add_caffeine_fluid(
    answers: NormalizedAnswers,
    water_cfg: dict[str, Any],
    low: float,
    high: float,
) -> tuple[float, float]:
    caffeine_cfg = water_cfg.get("caffeine_fluid") or {}
    if not caffeine_cfg.get("enabled"):
        return low, high
    cups_map = caffeine_cfg.get("cups_per_day_by_code") or {}
    code = answers.caffeine_frequency
    if code is None:
        return low, high
    cups = cups_map.get(str(code).strip())
    if cups is None:
        # Weekly / non-quantity codes are omitted by design.
        return low, high
    ml = float(caffeine_cfg.get("ml_per_cup") or 0.0)
    extra_l = float(cups) * ml / 1000.0
    return low + extra_l, high + extra_l


# ---------------------------------------------------------------------------
# Fibre
# ---------------------------------------------------------------------------


def _estimate_fibre(
    answers: NormalizedAnswers,
    fibre_cfg: dict[str, Any],
    confidence_cfg: dict[str, Any],
) -> FibreEstimate:
    note = str(fibre_cfg.get("note") or "")
    fields = (confidence_cfg.get("fibre") or {}).get("fields") or [
        "food_groups",
        "fresh_fruit_frequency",
        "fresh_vegetable_frequency",
    ]
    available_n = _count_present(answers, fields)
    confidence = _confidence_from_count(
        available_n, (confidence_cfg.get("fibre") or {}).get("by_available_count") or {}
    )
    if available_n == 0:
        return _fibre_unavailable(note)

    fruit_field = str(fibre_cfg.get("fruit_frequency_field") or "fresh_fruit_frequency")
    veg_field = str(fibre_cfg.get("vegetable_frequency_field") or "fresh_vegetable_frequency")
    fruit_code = getattr(answers, fruit_field, None)
    veg_code = getattr(answers, veg_field, None)
    selected_fibre_groups = _selected_fibre_group_codes(answers, fibre_cfg)

    if fruit_code is None and veg_code is None and not selected_fibre_groups:
        # Empty or non-fibre food_groups without produce is not enough
        # evidence to publish a personalised gram range.
        return _fibre_unavailable(note)

    per_serving = fibre_cfg.get("per_serving_g") or {}
    freq_map = fibre_cfg.get("frequency_to_servings_per_day") or {}
    staple = _range_pair(fibre_cfg.get("uncaptured_staple_fibre_g") or {}, default=(0.0, 0.0))
    central = _midpoint(staple)

    fruit_grams = _produce_fibre_central_g(
        fruit_code,
        freq_map,
        per_serving.get("fruit") or {},
    )
    if fruit_grams is not None:
        central += fruit_grams

    veg_grams = _produce_fibre_central_g(
        veg_code,
        freq_map,
        per_serving.get("vegetables") or {},
    )
    if veg_grams is not None:
        central += veg_grams

    if answers.food_groups is not None:
        central += _food_group_fibre_central_g(
            selected_fibre_groups,
            fibre_cfg,
            per_serving,
        )

    uncertainty_by_confidence = fibre_cfg.get("uncertainty_fraction_by_confidence") or {}
    uncertainty = float(uncertainty_by_confidence.get(confidence, 0.30))
    low = central * (1.0 - uncertainty)
    high = central * (1.0 + uncertainty)

    # Questionnaire fields indicate dietary patterns, not measured portions.
    # Bound uncertainty once around the combined estimate so uncertainty does
    # not multiply with every selected food source.
    plausible = _range_pair(
        fibre_cfg.get("plausible_range_g") or {},
        default=(0.0, 60.0),
    )
    low = max(plausible[0], low)
    high = min(plausible[1], high)

    # Public fibre range uses whole grams, same display style as macro percents.
    low = float(int(round(low)))
    high = float(int(round(high)))

    # Collapsed display (e.g. ~1–1) is too precise for this questionnaire.
    if low == high:
        return _fibre_unavailable(note)

    return FibreEstimate(
        low_g=low,
        high_g=high,
        tier=_fibre_tier(low, high, fibre_cfg),
        confidence=confidence,
        available=True,
        note=note,
    )


def _fibre_unavailable(note: str) -> FibreEstimate:
    return FibreEstimate(
        low_g=None,
        high_g=None,
        tier=None,
        confidence="INSUFFICIENT",
        available=False,
        note=note,
    )


def _selected_fibre_group_codes(answers: NormalizedAnswers, fibre_cfg: dict[str, Any]) -> set[str]:
    if answers.food_groups is None:
        return set()
    exclude = {str(x) for x in (fibre_cfg.get("exclude_food_group_codes_from_groups") or [])}
    group_map = fibre_cfg.get("food_group_fibre_map") or {}
    selected = {str(c) for c in answers.food_groups}
    return {
        str(code)
        for code in group_map
        if str(code) not in exclude and str(code) in selected
    }


def _produce_fibre_central_g(
    code: str | None,
    freq_map: dict[str, Any],
    per_serving: dict[str, Any],
) -> float | None:
    if code is None:
        return None
    band = _serving_band(freq_map.get(str(code).strip()))
    if band is None:
        return None
    grams = _range_pair(per_serving, default=(0.0, 0.0))
    return _midpoint(band) * _midpoint(grams)


def _food_group_fibre_central_g(
    selected_codes: set[str],
    fibre_cfg: dict[str, Any],
    per_serving: dict[str, Any],
) -> float:
    group_map = fibre_cfg.get("food_group_fibre_map") or {}
    presence = _serving_band(fibre_cfg.get("food_group_presence_servings_per_day"))
    if presence is None:
        return 0.0
    central = 0.0
    for code in selected_codes:
        kind = group_map.get(code) or group_map.get(str(code))
        if not kind:
            continue
        grams = _range_pair(per_serving.get(kind) or {}, default=(0.0, 0.0))
        central += _midpoint(presence) * _midpoint(grams)
    return central


def _midpoint(values: tuple[float, float]) -> float:
    return (values[0] + values[1]) / 2.0


def _serving_band(raw: Any) -> tuple[float, float] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        if raw.get("low") is None or raw.get("high") is None:
            return None
        return float(raw["low"]), float(raw["high"])
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value, value


def _range_pair(raw: Any, *, default: tuple[float, float]) -> tuple[float, float]:
    if isinstance(raw, dict) and raw.get("low") is not None and raw.get("high") is not None:
        return float(raw["low"]), float(raw["high"])
    return default


def _fibre_tier(low: float, high: float, fibre_cfg: dict[str, Any]) -> str:
    tiers = fibre_cfg.get("tiers") or {}
    matched: list[str] = []
    for _id, spec in tiers.items():
        label = str(spec.get("label") or _id)
        if _range_overlaps_tier(low, high, spec):
            matched.append(label)
    if not matched:
        return "Uncertain"
    if len(matched) == 1:
        return matched[0]
    joiner = str(fibre_cfg.get("crossing_joiner") or "–")
    return joiner.join(matched)


def _range_overlaps_tier(low: float, high: float, spec: dict[str, Any]) -> bool:
    min_inc = spec.get("min_inclusive")
    min_exc = spec.get("min_exclusive")
    max_inc = spec.get("max_inclusive")
    max_exc = spec.get("max_exclusive")
    tier_low = float("-inf")
    tier_high = float("inf")
    if min_inc is not None:
        tier_low = float(min_inc)
    if min_exc is not None:
        tier_low = float(min_exc) + 1e-9
    if max_inc is not None:
        tier_high = float(max_inc)
    if max_exc is not None:
        tier_high = float(max_exc) - 1e-9
    return low <= tier_high and high >= tier_low


# ---------------------------------------------------------------------------
# Carbohydrate pattern
# ---------------------------------------------------------------------------


def _estimate_carbohydrate(
    answers: NormalizedAnswers,
    carb_cfg: dict[str, Any],
    confidence_cfg: dict[str, Any],
) -> CarbohydratePattern:
    note = str(carb_cfg.get("note") or "")
    evidence = carb_cfg.get("evidence_fields") or []
    available_n = _count_present(answers, evidence)
    confidence = _confidence_from_count(
        available_n,
        (confidence_cfg.get("carbohydrate") or {}).get("by_available_count") or {},
    )
    labels = carb_cfg.get("labels") or {}

    if available_n == 0:
        label = str(labels.get("insufficient_information") or "Insufficient information")
        return CarbohydratePattern(
            pattern=label,
            confidence=confidence,
            available=False,
            note=note,
        )

    quality = 0
    for code, points in (carb_cfg.get("quality_food_group_points") or {}).items():
        if answers.food_groups is not None and str(code) in {str(c) for c in answers.food_groups}:
            quality += int(points)
    quality += _frequency_points(answers, carb_cfg.get("quality_frequency_points") or {})
    refined = _frequency_points(answers, carb_cfg.get("refined_frequency_points") or {})

    pattern_id = _match_rules(
        carb_cfg.get("rules") or [],
        available_fields=available_n,
        quality=quality,
        refined=refined,
        points=0,
        sources=0,
    )
    label = str(labels.get(pattern_id) or pattern_id)
    return CarbohydratePattern(
        pattern=label,
        confidence=confidence,
        available=True,
        note=note,
    )


# ---------------------------------------------------------------------------
# Protein source variety
# ---------------------------------------------------------------------------


def _estimate_protein(
    answers: NormalizedAnswers,
    protein_cfg: dict[str, Any],
    confidence_cfg: dict[str, Any],
) -> ProteinPattern:
    note = str(protein_cfg.get("note") or "")
    labels = protein_cfg.get("labels") or {}
    if answers.food_groups is None:
        return ProteinPattern(
            adequacy_tier=str(labels.get("insufficient_information") or "Insufficient information"),
            confidence="INSUFFICIENT",
            available=False,
            note=note,
        )

    applicable = _applicable_protein_groups(answers.diet_preference, protein_cfg)
    selected = {str(c) for c in answers.food_groups}
    sources = sum(1 for code in applicable if code in selected)

    red_cfg = protein_cfg.get("red_meat") or {}
    if _red_meat_counts(answers, red_cfg):
        sources += 1

    tier_id = "limited_source_variety"
    for spec in protein_cfg.get("tiers") or []:
        min_s = spec.get("min_sources")
        max_s = spec.get("max_sources")
        if min_s is not None and sources < int(min_s):
            continue
        if max_s is not None and sources > int(max_s):
            continue
        tier_id = str(spec.get("id") or tier_id)
        break

    pconf = confidence_cfg.get("protein") or {}
    if answers.diet_preference is not None:
        confidence = _as_confidence(pconf.get("food_groups_present_with_diet", "HIGH"))
    else:
        confidence = _as_confidence(pconf.get("food_groups_present", "MEDIUM"))

    return ProteinPattern(
        adequacy_tier=str(labels.get(tier_id) or tier_id),
        confidence=confidence,
        available=True,
        note=note,
    )


def _applicable_protein_groups(diet: str | None, protein_cfg: dict[str, Any]) -> set[str]:
    source_groups = {str(k) for k in (protein_cfg.get("source_food_groups") or {})}
    if diet is None:
        return source_groups
    mapping = protein_cfg.get("diet_applicable_groups") or {}
    allowed = mapping.get(str(diet).strip())
    if allowed is None:
        return source_groups
    return {str(c) for c in allowed if str(c) in source_groups}


def _red_meat_is_applicable(answers: NormalizedAnswers, red_cfg: dict[str, Any]) -> bool:
    if not red_cfg:
        return False
    if red_cfg.get("ignore_if_defaulted") and answers.red_meat_frequency_defaulted:
        return False
    diet = answers.diet_preference
    applicable = {str(x) for x in (red_cfg.get("applicable_diets") or [])}
    if diet is None or str(diet) not in applicable:
        return False
    return True


def _red_meat_counts(answers: NormalizedAnswers, red_cfg: dict[str, Any]) -> bool:
    if not _red_meat_is_applicable(answers, red_cfg):
        return False
    code = answers.red_meat_frequency
    if code is None:
        return False
    return str(code).strip() in {str(x) for x in (red_cfg.get("counts_as_source_codes") or [])}


# ---------------------------------------------------------------------------
# Fat tendency
# ---------------------------------------------------------------------------


def _estimate_fat(
    answers: NormalizedAnswers,
    fat_cfg: dict[str, Any],
    confidence_cfg: dict[str, Any],
) -> FatPattern:
    note = str(fat_cfg.get("note") or "")
    labels = fat_cfg.get("labels") or {}
    evidence = fat_cfg.get("evidence_fields") or []
    available_n = 0
    for field_name in evidence:
        value = getattr(answers, field_name, None)
        if field_name == "red_meat_frequency" and answers.red_meat_frequency_defaulted:
            continue
        if value is not None:
            available_n += 1
    confidence = _confidence_from_count(
        available_n, (confidence_cfg.get("fat") or {}).get("by_available_count") or {}
    )
    if available_n == 0:
        return FatPattern(
            tendency=str(labels.get("insufficient_information") or "Insufficient information"),
            confidence=confidence,
            available=False,
            note=note,
        )

    points = 0
    point_map = fat_cfg.get("high_tendency_points") or {}
    for field_name, code_points in point_map.items():
        if field_name == "red_meat_frequency" and fat_cfg.get("ignore_red_meat_if_defaulted"):
            if answers.red_meat_frequency_defaulted:
                continue
        raw = getattr(answers, field_name, None)
        if raw is None:
            continue
        points += int(code_points.get(str(raw).strip(), 0))

    tendency_id = _match_rules(
        fat_cfg.get("rules") or [],
        available_fields=available_n,
        quality=0,
        refined=0,
        points=points,
        sources=0,
    )
    return FatPattern(
        tendency=str(labels.get(tendency_id) or tendency_id),
        confidence=confidence,
        available=True,
        note=note,
    )


# ---------------------------------------------------------------------------
# Estimated C/P/F distribution (questionnaire-based, not measured)
# ---------------------------------------------------------------------------


def _estimate_macro_distribution(
    answers: NormalizedAnswers,
    macro_cfg: dict[str, Any],
    protein_cfg: dict[str, Any],
    *,
    carbohydrate_pattern: str | None,
    protein_pattern: str | None,
    fat_pattern: str | None,
) -> tuple[EstimatedMacroPercent | None, EstimatedMacroPercent | None, EstimatedMacroPercent | None]:
    """Estimate current C/P/F energy-share ranges from dietary questionnaire fields only."""
    if not macro_cfg:
        return None, None, None

    contributing = _macro_contributing_field_count(answers, macro_cfg)
    withhold_below = int(macro_cfg.get("withhold_below_fields") or 3)
    if contributing < withhold_below:
        return None, None, None
    if not _macro_minimum_signals_present(answers, macro_cfg):
        return None, None, None

    weights = macro_cfg.get("signal_weights") or {}
    max_delta = macro_cfg.get("max_delta") or {}
    baseline = macro_cfg.get("baseline") or {}
    bounds = _macro_bounds(macro_cfg)

    d_c = _clamp(
        _carbohydrate_delta(answers, macro_cfg, weights.get("carbohydrate") or {}),
        -float(max_delta.get("carbohydrate", 6)),
        float(max_delta.get("carbohydrate", 6)),
    )
    d_p = _clamp(
        _protein_delta(answers, macro_cfg, protein_cfg, weights.get("protein") or {}),
        -float(max_delta.get("protein", 5)),
        float(max_delta.get("protein", 5)),
    )
    d_f = _clamp(
        _fat_delta(answers, macro_cfg, protein_cfg, weights.get("fat") or {}),
        -float(max_delta.get("fat", 7)),
        float(max_delta.get("fat", 7)),
    )

    c = float(baseline.get("carbohydrate", 55)) + d_c
    p = float(baseline.get("protein", 13)) + d_p
    f = float(baseline.get("fat", 32)) + d_f
    c, p, f = _clamp_macros_to_bounds(c, p, f, bounds)
    c, p, f = _normalize_macros(c, p, f)
    c, p, f = _reclamp_and_renormalize_once(c, p, f, bounds)
    c, p, f = _reconcile_macro_sum(c, p, f)

    confidence, half_width = _macro_confidence(contributing, macro_cfg.get("confidence") or {})
    carb_est = _display_macro_percent(
        c, bounds["carbohydrate"], half_width, confidence, carbohydrate_pattern, macro_cfg
    )
    protein_est = _display_macro_percent(
        p, bounds["protein"], half_width, confidence, protein_pattern, macro_cfg
    )
    fat_est = _display_macro_percent(
        f, bounds["fat"], half_width, confidence, fat_pattern, macro_cfg
    )
    return carb_est, protein_est, fat_est


def _macro_contributing_field_count(answers: NormalizedAnswers, macro_cfg: dict[str, Any]) -> int:
    fields = macro_cfg.get("contributing_fields") or []
    count = 0
    for name in fields:
        if name == "red_meat_frequency" and answers.red_meat_frequency_defaulted:
            continue
        if getattr(answers, name, None) is not None:
            count += 1
    return count


def _macro_minimum_signals_present(answers: NormalizedAnswers, macro_cfg: dict[str, Any]) -> bool:
    required = macro_cfg.get("required_signals") or {}
    for _macro, fields in required.items():
        if not any(_macro_field_usable(answers, str(name)) for name in fields or []):
            return False
    return True


def _macro_field_usable(answers: NormalizedAnswers, name: str) -> bool:
    if name == "red_meat_frequency" and answers.red_meat_frequency_defaulted:
        return False
    return getattr(answers, name, None) is not None


def _carbohydrate_delta(
    answers: NormalizedAnswers,
    macro_cfg: dict[str, Any],
    carb_weights: dict[str, Any],
) -> float:
    dessert = _aliased_weight(
        answers.dessert_frequency, "dessert_frequency", macro_cfg, carb_weights.get("dessert") or {}
    )
    baked = _aliased_weight(
        answers.baked_goods_frequency,
        "baked_goods_frequency",
        macro_cfg,
        carb_weights.get("baked") or {},
    )
    return dessert + baked


def _protein_delta(
    answers: NormalizedAnswers,
    macro_cfg: dict[str, Any],
    protein_cfg: dict[str, Any],
    protein_weights: dict[str, Any],
) -> float:
    applicable = _applicable_protein_groups(answers.diet_preference, protein_cfg)
    selected = {str(c) for c in (answers.food_groups or ())}
    sources = (
        sum(1 for code in applicable if code in selected)
        if answers.food_groups is not None
        else 0
    )
    variety = _protein_variety_delta(
        sources,
        len(applicable),
        protein_weights.get("variety") or {},
        cap_to_applicable=bool(protein_weights.get("cap_rich_min_to_applicable_set", True)),
    )
    red_meat = 0.0
    if _red_meat_is_applicable(answers, protein_cfg.get("red_meat") or {}):
        red_meat = _aliased_weight(
            answers.red_meat_frequency,
            "red_meat_frequency",
            macro_cfg,
            protein_weights.get("red_meat") or {},
        )
    return variety + red_meat


def _protein_variety_delta(
    sources: int,
    n_applicable: int,
    variety_cfg: dict[str, Any],
    *,
    cap_to_applicable: bool,
) -> float:
    rich = variety_cfg.get("rich") or {}
    adequate = variety_cfg.get("adequate") or {}
    limited = variety_cfg.get("limited") or {}
    rich_min = int(rich.get("min_sources", 4))
    if cap_to_applicable and n_applicable > 0:
        rich_min = min(rich_min, n_applicable)
    if sources >= rich_min:
        return float(rich.get("delta", 4))
    adequate_min = int(adequate.get("min_sources", 2))
    adequate_max = int(adequate.get("max_sources", 3))
    if adequate_min <= sources <= adequate_max:
        return float(adequate.get("delta", 2))
    if sources <= int(limited.get("max_sources", 1)):
        return float(limited.get("delta", 0))
    return float(adequate.get("delta", 2))


def _fat_delta(
    answers: NormalizedAnswers,
    macro_cfg: dict[str, Any],
    protein_cfg: dict[str, Any],
    fat_weights: dict[str, Any],
) -> float:
    total = 0.0
    total += _aliased_weight(
        answers.butter_dish_frequency,
        "butter_dish_frequency",
        macro_cfg,
        fat_weights.get("butter") or {},
    )
    if _red_meat_is_applicable(answers, protein_cfg.get("red_meat") or {}):
        total += _aliased_weight(
            answers.red_meat_frequency,
            "red_meat_frequency",
            macro_cfg,
            fat_weights.get("red_meat") or {},
        )
    total += _aliased_weight(
        answers.baked_goods_frequency,
        "baked_goods_frequency",
        macro_cfg,
        fat_weights.get("baked") or {},
    )
    total += _aliased_weight(
        answers.dessert_frequency,
        "dessert_frequency",
        macro_cfg,
        fat_weights.get("dessert") or {},
    )
    codes = macro_cfg.get("food_group_codes") or {}
    if answers.food_groups is not None:
        selected = {str(c) for c in answers.food_groups}
        nuts_code = str(codes.get("nuts", "5"))
        dairy_code = str(codes.get("dairy", "2"))
        applicable = _applicable_protein_groups(answers.diet_preference, protein_cfg)
        if nuts_code in selected and (not applicable or nuts_code in applicable):
            total += float(fat_weights.get("nuts_present", 0))
        if dairy_code in selected and (not applicable or dairy_code in applicable):
            total += float(fat_weights.get("dairy_present", 0))
    return total


def _aliased_weight(
    code: str | None,
    field_name: str,
    macro_cfg: dict[str, Any],
    weight_map: dict[str, Any],
) -> float:
    if code is None:
        return 0.0
    aliases = (macro_cfg.get("frequency_aliases") or {}).get(field_name) or {}
    alias = aliases.get(str(code).strip())
    if alias is None:
        return 0.0
    return float(weight_map.get(str(alias), 0) or 0)


def _macro_bounds(macro_cfg: dict[str, Any]) -> dict[str, tuple[float, float]]:
    raw = macro_cfg.get("bounds") or {}
    out: dict[str, tuple[float, float]] = {}
    defaults = (("carbohydrate", (40.0, 65.0)), ("protein", (10.0, 25.0)), ("fat", (20.0, 40.0)))
    for name, default in defaults:
        pair = raw.get(name) or default
        out[name] = (float(pair[0]), float(pair[1]))
    return out


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _clamp_macros_to_bounds(
    c: float, p: float, f: float, bounds: dict[str, tuple[float, float]]
) -> tuple[float, float, float]:
    return (
        _clamp(c, *bounds["carbohydrate"]),
        _clamp(p, *bounds["protein"]),
        _clamp(f, *bounds["fat"]),
    )


def _normalize_macros(c: float, p: float, f: float) -> tuple[float, float, float]:
    total = c + p + f
    if total <= 0:
        return c, p, f
    return 100.0 * c / total, 100.0 * p / total, 100.0 * f / total


def _reclamp_and_renormalize_once(
    c: float, p: float, f: float, bounds: dict[str, tuple[float, float]]
) -> tuple[float, float, float]:
    values = {"carbohydrate": c, "protein": p, "fat": f}
    violators = [
        name
        for name, value in values.items()
        if value < bounds[name][0] or value > bounds[name][1]
    ]
    if not violators:
        return c, p, f

    clamped: dict[str, float] = {}
    for name in violators:
        clamped[name] = _clamp(values[name], *bounds[name])
    remaining = 100.0 - sum(clamped.values())
    others = [name for name in values if name not in clamped]
    other_total = sum(values[name] for name in others)
    redistributed: dict[str, float] = dict(clamped)
    if others and other_total > 0 and remaining > 0:
        for name in others:
            redistributed[name] = remaining * values[name] / other_total
    elif others and remaining > 0:
        share = remaining / len(others)
        for name in others:
            redistributed[name] = share
    else:
        redistributed = dict(values)
    c2, p2, f2 = (
        redistributed["carbohydrate"],
        redistributed["protein"],
        redistributed["fat"],
    )
    return _normalize_macros(c2, p2, f2)


def _reconcile_macro_sum(c: float, p: float, f: float) -> tuple[float, float, float]:
    total = c + p + f
    if total <= 0:
        return c, p, f
    c = 100.0 * c / total
    p = 100.0 * p / total
    f = 100.0 - c - p
    return c, p, f


def _macro_confidence(
    contributing: int, confidence_cfg: dict[str, Any]
) -> tuple[ConfidenceLevel, float]:
    min_half = float(confidence_cfg.get("min_half_width", 3))
    ordered = (
        ("HIGH", confidence_cfg.get("high") or {}),
        ("MEDIUM", confidence_cfg.get("medium") or {}),
        ("LOW", confidence_cfg.get("low") or {}),
    )
    for level, spec in ordered:
        if contributing >= int(spec.get("min_fields", 99)):
            width = max(float(spec.get("half_width", min_half)), min_half)
            return level, width  # type: ignore[return-value]
    return "INSUFFICIENT", max(8.0, min_half)


def _display_macro_percent(
    central: float,
    bounds: tuple[float, float],
    half_width: float,
    confidence: ConfidenceLevel,
    pattern: str | None,
    macro_cfg: dict[str, Any],
) -> EstimatedMacroPercent:
    rounding = int((macro_cfg.get("display") or {}).get("range_rounding", 1) or 1)
    lower = max(bounds[0], central - half_width)
    upper = min(bounds[1], central + half_width)
    lower_i = int(round(lower / rounding) * rounding)
    upper_i = int(round(upper / rounding) * rounding)
    lower_i = int(max(round(bounds[0]), min(round(bounds[1]), lower_i)))
    upper_i = int(max(round(bounds[0]), min(round(bounds[1]), upper_i)))
    if lower_i > upper_i:
        lower_i, upper_i = upper_i, lower_i
    return EstimatedMacroPercent(
        lower=lower_i,
        upper=upper_i,
        central=central,
        confidence=confidence,
        pattern=pattern,
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _count_present(answers: NormalizedAnswers, fields: list[str]) -> int:
    count = 0
    for name in fields:
        if not hasattr(answers, name):
            continue
        if getattr(answers, name) is not None:
            count += 1
    return count


def _frequency_points(answers: NormalizedAnswers, mapping: dict[str, Any]) -> int:
    total = 0
    for field_name, code_points in mapping.items():
        raw = getattr(answers, field_name, None)
        if raw is None:
            continue
        total += int(code_points.get(str(raw).strip(), 0))
    return total


def _match_rules(
    rules: list[Any],
    *,
    available_fields: int,
    quality: int,
    refined: int,
    points: int,
    sources: int,
) -> str:
    fallback = "insufficient_information"
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rule_id = str(rule.get("id") or fallback)
        if rule.get("fallback"):
            fallback = rule_id
            continue
        if "max_available_fields" in rule and available_fields > int(rule["max_available_fields"]):
            continue
        if "min_available_fields" in rule and available_fields < int(rule["min_available_fields"]):
            continue
        if "min_refined" in rule and refined < int(rule["min_refined"]):
            continue
        if "max_refined" in rule and refined > int(rule["max_refined"]):
            continue
        if "min_quality" in rule and quality < int(rule["min_quality"]):
            continue
        if "max_quality" in rule and quality > int(rule["max_quality"]):
            continue
        if "min_points" in rule and points < int(rule["min_points"]):
            continue
        if "max_points" in rule and points > int(rule["max_points"]):
            continue
        if "min_sources" in rule and sources < int(rule["min_sources"]):
            continue
        if "max_sources" in rule and sources > int(rule["max_sources"]):
            continue
        return rule_id
    return fallback


def _confidence_from_count(count: int, by_count: dict[str, Any]) -> ConfidenceLevel:
    raw = by_count.get(str(count), by_count.get(count, "INSUFFICIENT"))
    return _as_confidence(raw)


def _as_confidence(value: Any) -> ConfidenceLevel:
    text = str(value).strip().upper()
    if text in {"HIGH", "MEDIUM", "LOW", "INSUFFICIENT"}:
        return text  # type: ignore[return-value]
    return "INSUFFICIENT"
