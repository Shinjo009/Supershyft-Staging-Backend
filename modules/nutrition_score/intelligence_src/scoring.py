"""Scoring pipeline for the Nutrition Intelligence Engine.

Combines General Nutrition Quality, Goal Alignment, and Final Score blend.
Goal Alignment separates goal-critical and supporting behavioural proxies.
"""

from __future__ import annotations

from collections.abc import Mapping

from modules.nutrition_score.intelligence_src.config_loader import (
    NutritionEngineConfig,
    load_nutrition_engine_config,
)
from modules.nutrition_score.intelligence_src.models import (
    CombinedNutritionProfile,
    FinalScoreResult,
    GeneralQualityResult,
    GoalAlignmentResult,
    IndicatorScore,
    PriorityLevel,
)


# --- General Quality ---

def calculate_general_quality(
    indicators: Mapping[str, IndicatorScore],
    *,
    config: NutritionEngineConfig | None = None,
) -> GeneralQualityResult:
    """Weighted average of available behavioural indicator scores.

    Q = SUM(weight_i × score_i) / SUM(weight_i)

    Weights come from each indicator's ``general_quality_priority`` mapped
    through ``scoring.priority_level_weights``. Missing scores follow
    ``scoring.missing_indicator_policy`` (default: exclude_and_renormalize).
    """
    engine_config = config or load_nutrition_engine_config()
    scoring = engine_config.scoring
    level_weights = scoring.priority_level_weights
    policy = scoring.missing_indicator_policy

    used: list[str] = []
    missing: list[str] = []
    weights_used: dict[str, float] = {}
    weighted_sum = 0.0
    total_weight = 0.0

    # Deterministic iteration order.
    for indicator_id in sorted(indicators.keys()):
        item = indicators[indicator_id]
        weight = _general_quality_weight(item, level_weights, engine_config, indicator_id)
        if weight <= 0:
            # Priority "none" (or unknown) contributes nothing.
            if item.score is None:
                missing.append(indicator_id)
            continue

        if item.score is None:
            if policy == "treat_as_neutral":
                score = float(scoring.neutral_alignment_score)
                used.append(indicator_id)
                weights_used[indicator_id] = weight
                weighted_sum += weight * score
                total_weight += weight
            else:
                # exclude_and_renormalize (default): skip numerator and denominator.
                missing.append(indicator_id)
            continue

        score = float(item.score)
        used.append(indicator_id)
        weights_used[indicator_id] = weight
        weighted_sum += weight * score
        total_weight += weight

    if total_weight <= 0:
        return GeneralQualityResult(
            general_quality=None,
            indicators_used=tuple(used),
            indicators_missing=tuple(missing),
            total_weight=0.0,
            weights_used={},
        )

    quality = weighted_sum / total_weight
    if quality < 0.0:
        quality = 0.0
    elif quality > 100.0:
        quality = 100.0

    return GeneralQualityResult(
        general_quality=quality,
        indicators_used=tuple(used),
        indicators_missing=tuple(missing),
        total_weight=total_weight,
        weights_used=dict(weights_used),
    )

def _general_quality_weight(
    item: IndicatorScore,
    level_weights: dict[PriorityLevel, float],
    config: NutritionEngineConfig,
    indicator_id: str,
) -> float:
    priority = item.general_quality_priority
    if priority is None:
        definition = config.indicators.get(indicator_id)
        if definition is not None:
            priority = definition.general_quality_priority
    if priority is None:
        return 0.0
    return float(level_weights.get(priority, 0.0))

# --- Goal Alignment ---

def calculate_goal_alignment(
    indicators: Mapping[str, IndicatorScore],
    combined_profile: CombinedNutritionProfile,
    *,
    config: NutritionEngineConfig | None = None,
) -> GoalAlignmentResult:
    """Blend goal-critical and supporting behavioural alignment.

    Critical indicators (``very_high``/``high``) and supporting indicators
    (``medium``/``low``) are each renormalized over available questionnaire
    data, then blended using the configured tier weights. This prevents broad
    general-quality behaviour from diluting a poor goal-critical pattern.

    Zero goals → ``goal_alignment=None`` (``zero_goal_mode`` is handled in Phase 10).
    """
    engine_config = config or load_nutrition_engine_config()
    scoring = engine_config.scoring
    level_weights = scoring.priority_level_weights
    policy = scoring.missing_indicator_policy

    if not combined_profile.goals:
        return GoalAlignmentResult(
            goal_alignment=None,
            indicators_used=(),
            indicators_missing=(),
            total_weight=0.0,
            weights_used={},
        )

    used: list[str] = []
    missing: list[str] = []
    weights_used: dict[str, float] = {}
    weighted_sums = {"critical": 0.0, "supporting": 0.0}
    total_weights = {"critical": 0.0, "supporting": 0.0}

    # Deterministic iteration order.
    for indicator_id in sorted(indicators.keys()):
        item = indicators[indicator_id]
        priority = combined_profile.priority_levels.get(indicator_id)
        weight = float(level_weights.get(priority, 0.0)) if priority is not None else 0.0
        if weight <= 0:
            if item.score is None:
                missing.append(indicator_id)
            continue
        tier = "critical" if priority in {"very_high", "high"} else "supporting"

        if item.score is None:
            if policy == "treat_as_neutral":
                score = float(scoring.neutral_alignment_score)
                used.append(indicator_id)
                weights_used[indicator_id] = weight
                weighted_sums[tier] += weight * score
                total_weights[tier] += weight
            else:
                # exclude_and_renormalize (default): skip numerator and denominator.
                missing.append(indicator_id)
            continue

        score = float(item.score)
        used.append(indicator_id)
        weights_used[indicator_id] = weight
        weighted_sums[tier] += weight * score
        total_weights[tier] += weight

    total_weight = sum(total_weights.values())
    if total_weight <= 0:
        return GoalAlignmentResult(
            goal_alignment=None,
            indicators_used=tuple(used),
            indicators_missing=tuple(missing),
            total_weight=0.0,
            weights_used={},
        )

    critical_score = _weighted_pool_score(
        weighted_sums["critical"],
        total_weights["critical"],
    )
    supporting_score = _weighted_pool_score(
        weighted_sums["supporting"],
        total_weights["supporting"],
    )
    tier_components = (
        (critical_score, float(scoring.goal_critical_weight)),
        (supporting_score, float(scoring.goal_supporting_weight)),
    )
    usable_tier_weight = sum(
        weight for score, weight in tier_components if score is not None and weight > 0
    )
    if usable_tier_weight <= 0:
        return GoalAlignmentResult(
            goal_alignment=None,
            indicators_used=tuple(used),
            indicators_missing=tuple(missing),
            total_weight=total_weight,
            weights_used=dict(weights_used),
        )
    alignment = sum(
        float(score) * weight
        for score, weight in tier_components
        if score is not None and weight > 0
    ) / usable_tier_weight
    if alignment < 0.0:
        alignment = 0.0
    elif alignment > 100.0:
        alignment = 100.0

    return GoalAlignmentResult(
        goal_alignment=alignment,
        indicators_used=tuple(used),
        indicators_missing=tuple(missing),
        total_weight=total_weight,
        weights_used=dict(weights_used),
    )


def _weighted_pool_score(weighted_sum: float, total_weight: float) -> float | None:
    if total_weight <= 0:
        return None
    return weighted_sum / total_weight


# --- Final Score ---

def calculate_final_score(
    general_quality: float | None,
    goal_alignment: float | None,
    *,
    config: NutritionEngineConfig | None = None,
) -> FinalScoreResult:
    """Blend Q and A into the final nutrition behaviour score.

    When both are available:
        Final = Wq × Q + Wa × A

    Weights come from ``scoring.general_quality_weight`` /
    ``scoring.goal_alignment_weight``. Missing components are not treated as
    zero; usable weight is renormalized (see ``zero_goal_mode``).
    """
    engine_config = config or load_nutrition_engine_config()
    scoring = engine_config.scoring
    wq_cfg = float(scoring.general_quality_weight)
    wa_cfg = float(scoring.goal_alignment_weight)

    q = general_quality
    a = goal_alignment

    # Optional: synthesize neutral alignment when policy requests it and A is missing.
    if a is None and q is not None and scoring.zero_goal_mode == "use_neutral_alignment":
        a = float(scoring.neutral_alignment_score)

    q_usable = q is not None
    a_usable = a is not None

    if not q_usable and not a_usable:
        return FinalScoreResult(
            final_score=None,
            general_quality=general_quality,
            goal_alignment=goal_alignment,
            general_quality_weight_used=0.0,
            goal_alignment_weight_used=0.0,
        )

    if q_usable and a_usable:
        wq = wq_cfg
        wa = wa_cfg
        total = wq + wa
        if total <= 0:
            return FinalScoreResult(
                final_score=None,
                general_quality=general_quality,
                goal_alignment=goal_alignment,
                general_quality_weight_used=0.0,
                goal_alignment_weight_used=0.0,
            )
        # Defensive renormalize if config weights do not already sum to 1.
        wq_used = wq / total
        wa_used = wa / total
        score = wq_used * float(q) + wa_used * float(a)
    elif q_usable:
        # renormalize_quality_only (and any A-missing case under that mode): Final = Q
        wq_used = 1.0
        wa_used = 0.0
        score = float(q)
    else:
        # Only alignment usable — do not treat missing Q as 0.
        wq_used = 0.0
        wa_used = 1.0
        score = float(a)  # type: ignore[arg-type]

    if score < 0.0:
        score = 0.0
    elif score > 100.0:
        score = 100.0

    return FinalScoreResult(
        final_score=score,
        general_quality=general_quality,
        goal_alignment=goal_alignment,
        general_quality_weight_used=wq_used,
        goal_alignment_weight_used=wa_used,
    )

def display_nutrition_score(final_score: float | None) -> int | None:
    """Whole-number display for Nutrition Score (e.g. 27, not 27.44).

    Does not alter the internal float used for calculations.
    """
    if final_score is None:
        return None
    return int(round(float(final_score)))


def resolve_risk_band(
    final_score: float | None,
    *,
    config: NutritionEngineConfig | None = None,
) -> str | None:
    """Map a final nutrition score to a single risk_band label.

    Iterates ``scoring.score_bands`` (sorted descending by ``min_score``)
    and returns the first band whose ``min_score <= final_score``.
    Returns ``None`` when *final_score* is ``None``.
    """
    if final_score is None:
        return None
    engine_config = config or load_nutrition_engine_config()
    for band in sorted(
        engine_config.scoring.score_bands,
        key=lambda item: item.min_score,
        reverse=True,
    ):
        if final_score >= band.min_score:
            return band.label
    return None

