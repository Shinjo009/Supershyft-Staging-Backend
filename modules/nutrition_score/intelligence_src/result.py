"""Phase 13 user-facing nutrition result composer.

Combines Nutrition Score + current consumption + goal-based targets.
Does not recalculate scoring or targets; does not expose Q/A internals.
"""

from __future__ import annotations

from modules.nutrition_score.intelligence_src.scoring import calculate_goal_alignment
from modules.nutrition_score.intelligence_src.behaviour import evaluate_behaviour_indicators
from modules.nutrition_score.intelligence_src.body_metrics import resolve_ideal_body_metrics
from modules.nutrition_score.intelligence_src.goals import combine_goal_profiles
from modules.nutrition_score.intelligence_src.config_loader import (
    NutritionEngineConfig,
    load_nutrition_engine_config,
)
from modules.nutrition_score.intelligence_src.nutrition import estimate_current_nutrition
from modules.nutrition_score.intelligence_src.goals import load_goal_profiles
from modules.nutrition_score.intelligence_src.goals import resolve_goals
from modules.nutrition_score.intelligence_src.models import (
    EstimatedMacroPercent,
    EstimatedNutritionIntake,
    NormalizedAnswers,
    NutritionTargets,
    NutritionUserResult,
    TargetRange,
)
from modules.nutrition_score.intelligence_src.scoring import calculate_general_quality
from modules.nutrition_score.intelligence_src.scoring import (
    calculate_final_score,
    display_nutrition_score,
    resolve_risk_band,
)
from modules.nutrition_score.intelligence_src.targets import generate_nutrition_targets


_PATTERN_NOTE = "Actual intake may vary."
_DISCLAIMER = (
    "Questionnaire-based estimate, not a measured intake."
)
_WITHHOLD_MACRO = "Not enough information to estimate your dietary distribution."


def compose_user_result(
    answers: NormalizedAnswers,
    *,
    config: NutritionEngineConfig | None = None,
) -> NutritionUserResult:
    """Compose the user-facing result from existing Phase 4–12 engines."""
    engine = config or load_nutrition_engine_config()
    goals = resolve_goals(answers)
    profiles = load_goal_profiles(goals, config=engine)
    combined = combine_goal_profiles(profiles, config=engine)
    indicators = evaluate_behaviour_indicators(answers, config=engine)
    quality = calculate_general_quality(indicators, config=engine)
    alignment = calculate_goal_alignment(indicators, combined, config=engine)
    final = calculate_final_score(
        quality.general_quality,
        alignment.goal_alignment,
        config=engine,
    )
    current = estimate_current_nutrition(answers, config=engine)
    ideal = generate_nutrition_targets(combined, answers, config=engine)
    ideal_body_metrics = resolve_ideal_body_metrics(
        answers,
        combined,
        config=engine,
    )
    return NutritionUserResult(
        nutrition_score=display_nutrition_score(final.final_score),
        nutrition_score_raw=final.final_score,
        current_nutrition=current,
        goal_based_ideal=ideal,
        goals=tuple(goals),
        risk_band=resolve_risk_band(final.final_score, config=engine),
        ideal_body_metrics=ideal_body_metrics,
        disclaimer=_DISCLAIMER,
    )


def format_user_result(
    result: NutritionUserResult,
    *,
    config: NutritionEngineConfig | None = None,
) -> str:
    """Simple user-facing text. Does not print Q/A or indicator internals."""
    engine = config or load_nutrition_engine_config()
    current = result.current_nutrition
    ideal = result.goal_based_ideal
    score_line = (
        f"{result.nutrition_score} / 100"
        if result.nutrition_score is not None
        else "Not enough information"
    )
    goal_names = _goal_display_names(result.goals, engine)

    display = ((engine.consumption or {}).get("macro_distribution") or {}).get("display") or {}
    heading = str(display.get("heading") or "ESTIMATED DIETARY DISTRIBUTION")
    subheading = str(display.get("subheading") or "From your questionnaire")
    withhold = str(
        ((engine.consumption or {}).get("macro_distribution") or {}).get("withhold_message")
        or _WITHHOLD_MACRO
    )

    lines = [
        "Nutrition Score",
        score_line,
        "",
        "--------------------------------",
        "",
        "YOUR CURRENT NUTRITION",
        "",
        heading,
        subheading,
        "",
        *_current_macro_lines(current, withhold),
        "Fibre",
        *_current_fibre_lines(current),
        "",
        "Water",
        _current_water_line(current),
        "",
        "--------------------------------",
        "",
        "YOUR GOAL-BASED IDEAL",
        "",
    ]
    if goal_names:
        lines.extend(["Goals: " + ", ".join(goal_names), ""])
    lines.extend(_ideal_lines(ideal))
    lines.extend(
        [
            "",
            result.disclaimer,
            _PATTERN_NOTE,
            "",
        ]
    )
    return "\n".join(lines)


def _goal_display_names(goals: tuple[str, ...], config: NutritionEngineConfig) -> list[str]:
    names: list[str] = []
    for goal_id in goals:
        profile = config.goals.get(goal_id)  # type: ignore[arg-type]
        names.append(profile.display_name if profile is not None else str(goal_id))
    return names


def _current_macro_lines(
    current: EstimatedNutritionIntake,
    withhold: str,
) -> list[str]:
    carb = current.estimated_carbohydrate_percent
    protein = current.estimated_protein_percent
    fat = current.estimated_fat_percent

    if carb is None or protein is None or fat is None:
        return [
            withhold,
            "",
            "Carbohydrates",
            "Not enough information",
            "",
            "Protein",
            "Not enough information",
            "",
            "Fat",
            "Not enough information",
            "",
        ]

    return [
        "Carbohydrates",
        _fmt_estimated_percent(carb),
        "",
        "Protein",
        _fmt_estimated_percent(protein),
        "",
        "Fat",
        _fmt_estimated_percent(fat),
        "",
    ]


def _fmt_estimated_percent(estimate: EstimatedMacroPercent) -> str:
    return f"~{estimate.lower}–{estimate.upper}%"


def _current_pattern_line(available: bool, label: str | None) -> str:
    if not available or not label:
        return "Not enough information"
    return label


def _current_fibre_lines(current: EstimatedNutritionIntake) -> list[str]:
    fibre = current.fibre

    if not fibre.available or fibre.low_g is None or fibre.high_g is None:
        return ["Not enough information"]

    return [f"~{_fmt_g(fibre.low_g)}–{_fmt_g(fibre.high_g)} g/day"]

def _current_water_line(current: EstimatedNutritionIntake) -> str:
    water = current.water
    if not water.available or water.low_l is None or water.high_l is None:
        return "Not enough information"
    return f"~{_fmt_l(water.low_l)}–{_fmt_l(water.high_l)} L/day"


def _ideal_lines(ideal: NutritionTargets | None) -> list[str]:
    if ideal is None:
        return ["Not enough information"]
    return [
        "Carbohydrates",
        _fmt_percent(ideal.carbohydrate_percent),
        "",
        "Protein",
        _fmt_percent(ideal.protein_percent),
        "",
        "Fat",
        _fmt_percent(ideal.fat_percent),
        "",
        "Fibre",
        _fmt_grams(ideal.fibre_g),
        "",
        "Water",
        _fmt_litres(ideal.water_l),
    ]


def _fmt_percent(value: TargetRange | None) -> str:
    if value is None or (value.low is None and value.high is None):
        return "Not enough information"
    return f"{_strip_num(value.low)}–{_strip_num(value.high)}%"


def _fmt_grams(value: TargetRange | None) -> str:
    if value is None or (value.low is None and value.high is None):
        return "Not enough information"
    return f"{_strip_num(value.low)}–{_strip_num(value.high)} g/day"


def _fmt_litres(value: TargetRange | None) -> str:
    if value is None or (value.low is None and value.high is None):
        return "Not enough information"
    return f"{_fmt_l(value.low)}–{_fmt_l(value.high)} L/day"


def _fmt_g(value: float) -> str:
    return str(int(round(value)))


def _fmt_l(value: float | None) -> str:
    if value is None:
        return "—"
    text = f"{value:.1f}"
    if text.endswith(".0"):
        return text[:-2]
    return text


def _strip_num(value: float | None) -> str:
    if value is None:
        return "—"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"
