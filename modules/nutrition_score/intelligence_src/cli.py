"""Interactive local tester for the Nutrition Intelligence Engine (Phases 1–10).

Developer tool only — not a production API/UI.

Usage:
    python -m intelligence_src.cli
    python -m intelligence_src.cli --debug

Collects questionnaire answers using labels/codes from the existing Metsights
seed questionnaire, builds a ReportsService-style lookup, runs the existing
normalizer + Phases 4–10, and prints a human-readable result.

Does not implement targets, intake estimates, ReportsService integration,
or Phase 11+.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import asdict, is_dataclass
from pprint import pformat
from typing import Any, TextIO

from modules.nutrition_score.intelligence_src.scoring import calculate_goal_alignment
from modules.nutrition_score.intelligence_src.behaviour import evaluate_behaviour_indicators
from modules.nutrition_score.intelligence_src.goals import combine_goal_profiles
from modules.nutrition_score.intelligence_src.config_loader import (
    NutritionEngineConfig,
    load_nutrition_engine_config,
)
from modules.nutrition_score.intelligence_src.goals import load_goal_profiles
from modules.nutrition_score.intelligence_src.goals import resolve_goals
from modules.nutrition_score.intelligence_src.models import (
    IndicatorScore,
    NormalizedAnswers,
)
from modules.nutrition_score.intelligence_src.questionnaire import normalize_questionnaire_lookup
from modules.nutrition_score.intelligence_src.scoring import calculate_general_quality
from modules.nutrition_score.intelligence_src.result import compose_user_result, format_user_result
from modules.nutrition_score.intelligence_src.scoring import (
    calculate_final_score,
    display_nutrition_score,
)
from modules.nutrition_score.intelligence_src.targets import generate_nutrition_targets

# Fields that currently feed Phases 7–10 scoring (via indicators.yaml / goals).
# diet_preference is context for protein_supporting_foods only.
_SCORING_QUESTION_KEYS: tuple[str, ...] = (
    "health_priorities",
    "diet_preference",
    "food_groups",
    "healthy_breakfast_frequency",
    "fresh_fruit_frequency",
    "fresh_vegetable_frequency",
    "baked_goods_frequency",
    "dessert_frequency",
    "butter_dish_frequency",
    "red_meat_frequency",
    "extra_salt_frequency",
    "water_intake_frequency",
    "caffeine_frequency",
)

_INDICATOR_DISPLAY_ORDER: tuple[tuple[str, str], ...] = (
    ("fruit_intake", "Fruit intake"),
    ("vegetable_intake", "Vegetable intake"),
    ("food_diversity", "Food diversity"),
    ("protein_supporting_foods", "Protein supporting foods"),
    ("meal_regularity", "Meal regularity"),
    ("baked_goods_control", "Baked goods control"),
    ("dessert_sugar_control", "Dessert/sugar control"),
    ("hydration", "Hydration"),
    ("sodium_control", "Sodium control"),
)

_STRONG_THRESHOLD = 75.0
_IMPROVE_THRESHOLD = 40.0


# ---------------------------------------------------------------------------
# Questionnaire catalog (from existing seed — not invented)
# ---------------------------------------------------------------------------


def build_questionnaire_catalog() -> dict[str, dict[str, Any]]:
    """Map question_key → {prompt, type, options: [(code, label), ...]} from seed.

    The catalog is the Metsights questionnaire snapshot exported into
    ``config/questionnaire_catalog.json``. Labels and codes are not invented.
    """
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent / "config" / "questionnaire_catalog.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    catalog: dict[str, dict[str, Any]] = {}
    for key, meta in raw.items():
        options = meta.get("options") or []
        catalog[str(key)] = {
            "question_key": str(meta.get("question_key") or key),
            "prompt": meta.get("prompt"),
            "question_type": meta.get("question_type"),
            "options": [(str(code), str(label)) for code, label in options],
        }
    return catalog


def build_option_reverse_map(catalog: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Build label/code → option_value maps compatible with the normalizer."""
    reverse: dict[str, dict[str, str]] = {}
    for key, meta in catalog.items():
        mapping: dict[str, str] = {}
        for code, label in meta["options"]:
            mapping[str(code)] = str(code)
            mapping[str(label)] = str(code)
            mapping[str(label).strip().lower()] = str(code)
        reverse[key] = mapping
    return reverse


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------


def _prompt_line(prompt: str, *, infile: TextIO, outfile: TextIO) -> str:
    outfile.write(prompt)
    outfile.flush()
    line = infile.readline()
    if line == "":
        raise EOFError("stdin closed")
    return line.strip()


def ask_single_choice(
    *,
    title: str,
    prompt: str,
    options: Sequence[tuple[str, str]],
    allow_skip: bool,
    infile: TextIO,
    outfile: TextIO,
) -> str | None:
    outfile.write(f"\n{title}\n{prompt}\n")
    for index, (code, label) in enumerate(options, start=1):
        outfile.write(f"  {index}. {label}  [code={code}]\n")
    if allow_skip:
        outfile.write("  Enter = skip\n")
    while True:
        raw = _prompt_line("Select number (or option code): ", infile=infile, outfile=outfile)
        if not raw:
            if allow_skip:
                return None
            outfile.write("Selection required.\n")
            continue
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1][0]
        for code, _label in options:
            if raw == code:
                return code
        outfile.write("Invalid selection. Try again.\n")


def ask_multi_choice(
    *,
    title: str,
    prompt: str,
    options: Sequence[tuple[str, str]],
    allow_skip: bool,
    allow_empty: bool,
    max_selections: int | None,
    infile: TextIO,
    outfile: TextIO,
) -> list[str] | None:
    outfile.write(f"\n{title}\n{prompt}\n")
    for index, (code, label) in enumerate(options, start=1):
        outfile.write(f"  {index}. {label}  [code={code}]\n")
    hint = "Enter comma-separated numbers (e.g. 1,3,4)"
    if max_selections is not None:
        hint += f"; max {max_selections}"
    if allow_skip:
        hint += "; Enter = skip"
    outfile.write(f"{hint}\n")
    while True:
        raw = _prompt_line("Select: ", infile=infile, outfile=outfile)
        if not raw:
            if allow_skip:
                return None
            if allow_empty:
                return []
            outfile.write("Selection required.\n")
            continue
        parts = [p.strip() for p in raw.replace(" ", "").split(",") if p.strip()]
        codes: list[str] = []
        seen: set[str] = set()
        ok = True
        for part in parts:
            code: str | None = None
            if part.isdigit():
                idx = int(part)
                if 1 <= idx <= len(options):
                    code = options[idx - 1][0]
            if code is None:
                for opt_code, _label in options:
                    if part == opt_code:
                        code = opt_code
                        break
            if code is None:
                outfile.write(f"Invalid item: {part!r}\n")
                ok = False
                break
            if code in seen:
                continue
            seen.add(code)
            codes.append(code)
        if not ok:
            continue
        if max_selections is not None and len(codes) > max_selections:
            outfile.write(f"Select at most {max_selections} option(s).\n")
            continue
        if not codes and not allow_empty:
            outfile.write("Selection required.\n")
            continue
        return codes


def collect_questionnaire_lookup(
    catalog: dict[str, dict[str, Any]],
    *,
    infile: TextIO | None = None,
    outfile: TextIO | None = None,
) -> dict[str, Any]:
    """Interactively collect a ReportsService-style questionnaire lookup."""
    infile = infile if infile is not None else sys.stdin
    outfile = outfile if outfile is not None else sys.stdout
    outfile.write(
        "\nNutrition Intelligence Engine — local questionnaire tester\n"
        "Answers use existing Metsights questionnaire codes/labels.\n"
        "Phases 1–10 only (no targets / no production integration).\n"
    )
    lookup: dict[str, Any] = {}

    # Goals first (0–2), using seed health_priorities options.
    goals_meta = catalog["health_priorities"]
    selected_goals = ask_multi_choice(
        title="Health priorities (goals)",
        prompt=goals_meta["prompt"],
        options=goals_meta["options"],
        allow_skip=True,
        allow_empty=True,
        max_selections=2,
        infile=infile,
        outfile=outfile,
    )
    if selected_goals is None or selected_goals == []:
        # Explicit zero goals: omit field or empty list — normalizer → ().
        lookup["health_priorities"] = []
    elif len(selected_goals) == 1:
        lookup["health_priorities"] = selected_goals[0]
    else:
        lookup["health_priorities"] = selected_goals

    for key in _SCORING_QUESTION_KEYS:
        if key == "health_priorities":
            continue
        meta = catalog[key]
        options = meta["options"]
        prompt = meta["prompt"]
        if key == "food_groups":
            values = ask_multi_choice(
                title=key,
                prompt=prompt,
                options=options,
                allow_skip=True,
                allow_empty=True,
                max_selections=None,
                infile=infile,
                outfile=outfile,
            )
            if values is not None:
                lookup[key] = values
            continue

        value = ask_single_choice(
            title=key,
            prompt=prompt,
            options=options,
            allow_skip=True,
            infile=infile,
            outfile=outfile,
        )
        if value is not None:
            lookup[key] = value

    return lookup


# ---------------------------------------------------------------------------
# Pipeline (existing engine only)
# ---------------------------------------------------------------------------


def run_pipeline(
    lookup: dict[str, Any],
    *,
    config: NutritionEngineConfig | None = None,
    option_reverse_map: dict[str, dict[str, str]] | None = None,
    user_gender: str | None = None,
) -> dict[str, Any]:
    """Normalize + Phases 4–10. No target generation."""
    engine_config = config or load_nutrition_engine_config()
    normalized = normalize_questionnaire_lookup(
        lookup,
        user_gender=user_gender,
        option_reverse_map=option_reverse_map,
    )
    goals = resolve_goals(normalized)
    profiles = load_goal_profiles(goals, config=engine_config)
    combined = combine_goal_profiles(profiles, config=engine_config)
    indicators = evaluate_behaviour_indicators(normalized, config=engine_config)
    quality = calculate_general_quality(indicators, config=engine_config)
    alignment = calculate_goal_alignment(indicators, combined, config=engine_config)
    final = calculate_final_score(
        quality.general_quality,
        alignment.goal_alignment,
        config=engine_config,
    )
    targets = generate_nutrition_targets(combined, normalized, config=engine_config)
    user_result = compose_user_result(normalized, config=engine_config)
    return {
        "lookup": lookup,
        "normalized": normalized,
        "goals": tuple(goals),
        "profiles": profiles,
        "combined": combined,
        "indicators": indicators,
        "quality": quality,
        "alignment": alignment,
        "final": final,
        "targets": targets,
        "user_result": user_result,
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def _fmt_score(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "N/A (insufficient data)"
    return f"{value:.{digits}f}"


def _fmt_range(value: Any) -> str:
    if value is None:
        return "N/A"
    low = getattr(value, "low", None)
    high = getattr(value, "high", None)
    unit = getattr(value, "unit", None) or ""
    if low is None and high is None:
        mode = getattr(value, "mode", None)
        return f"mode={mode}" if mode else "N/A"
    unit_s = f" {unit}" if unit else ""
    return f"{low}–{high}{unit_s}"


def _goal_labels(goals: Sequence[str], config: NutritionEngineConfig) -> list[str]:
    labels: list[str] = []
    for goal_id in goals:
        profile = config.goals.get(goal_id)  # type: ignore[arg-type]
        if profile is not None:
            labels.append(profile.display_name)
        else:
            labels.append(str(goal_id))
    return labels


def format_result(result: dict[str, Any], *, config: NutritionEngineConfig) -> str:
    goals = result["goals"]
    indicators: dict[str, IndicatorScore] = result["indicators"]
    quality = result["quality"].general_quality
    alignment = result["alignment"].goal_alignment
    final = result["final"].final_score
    display_final = display_nutrition_score(final)
    targets = result.get("targets")

    lines = [
        "",
        "========================================",
        "NUTRITION INTELLIGENCE RESULT",
        "========================================",
        "",
        "GOALS",
    ]
    labels = _goal_labels(goals, config)
    if labels:
        for label in labels:
            lines.append(label)
    else:
        lines.append("(none)")

    lines.extend(
        [
            "",
            "BEHAVIOUR INDICATORS",
            "----------------------------------------",
        ]
    )
    for indicator_id, display in _INDICATOR_DISPLAY_ORDER:
        item = indicators.get(indicator_id)
        score = None if item is None else item.score
        lines.append(f"{display:<32} {_fmt_score(score)}")

    lines.extend(
        [
            "",
            "GENERAL NUTRITION QUALITY",
            "----------------------------------------",
            f"{_fmt_score(quality)} / 100" if quality is not None else _fmt_score(quality),
            "",
            "GOAL ALIGNMENT",
            "----------------------------------------",
            f"{_fmt_score(alignment)} / 100" if alignment is not None else _fmt_score(alignment),
            "",
            "FINAL NUTRITION SCORE",
            "----------------------------------------",
            (
                f"{display_final} / 100"
                if display_final is not None
                else _fmt_score(final)
            ),
        ]
    )

    if targets is not None:
        lines.extend(
            [
                "",
                "NUTRITION TARGETS (not intake)",
                "----------------------------------------",
                f"Carbohydrate %: {_fmt_range(targets.carbohydrate_percent)}",
                f"Protein %:      {_fmt_range(targets.protein_percent)}",
                f"Fat %:          {_fmt_range(targets.fat_percent)}",
                f"Fibre g:        {_fmt_range(targets.fibre_g)}",
                f"Water L:        {_fmt_range(targets.water_l)}",
                f"Protein g/kg:   {_fmt_range(targets.protein_g_per_kg)}",
                f"Carb g/kg:      {_fmt_range(targets.carbohydrate_g_per_kg)}",
                f"Activity band:  {targets.activity_band}",
            ]
        )

    lines.extend(
        [
            "",
            "========================================",
            "",
            "SCORE BREAKDOWN",
            "----------------------------------------",
            "",
            "Strong areas:",
        ]
    )
    strong = [
        display
        for indicator_id, display in _INDICATOR_DISPLAY_ORDER
        if (item := indicators.get(indicator_id)) is not None
        and item.score is not None
        and item.score >= _STRONG_THRESHOLD
    ]
    improve = [
        display
        for indicator_id, display in _INDICATOR_DISPLAY_ORDER
        if (item := indicators.get(indicator_id)) is not None
        and item.score is not None
        and item.score <= _IMPROVE_THRESHOLD
    ]
    if strong:
        for name in strong:
            lines.append(f"- {name}")
    else:
        lines.append("- (none above threshold)")

    lines.extend(["", "Areas needing improvement:"])
    if improve:
        for name in improve:
            lines.append(f"- {name}")
    else:
        lines.append("- (none below threshold)")

    lines.extend(
        [
            "",
            f"General Quality: {_fmt_score(quality)}",
            f"Goal Alignment: {_fmt_score(alignment)}",
            "",
        ]
    )
    return "\n".join(lines)


def _to_debug_obj(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return {k: _to_debug_obj(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_debug_obj(v) for v in value]
    return value


def format_debug(result: dict[str, Any]) -> str:
    sections = [
        ("RAW LOOKUP", result["lookup"]),
        ("NORMALIZED INPUT", _to_debug_obj(result["normalized"])),
        ("RESOLVED GOALS", list(result["goals"])),
        ("GOAL PROFILES", _to_debug_obj(result["profiles"])),
        ("COMBINED PROFILE", _to_debug_obj(result["combined"])),
        ("INDICATOR SCORES", _to_debug_obj(result["indicators"])),
        ("GENERAL QUALITY", _to_debug_obj(result["quality"])),
        ("GOAL ALIGNMENT", _to_debug_obj(result["alignment"])),
        ("FINAL SCORE", _to_debug_obj(result["final"])),
    ]
    chunks = ["", "======== DEBUG ========"]
    for title, payload in sections:
        chunks.append("")
        chunks.append(title)
        chunks.append("-" * len(title))
        chunks.append(pformat(payload, sort_dicts=False, width=100))
    chunks.append("")
    chunks.append("======== END DEBUG ========")
    chunks.append("")
    return "\n".join(chunks)


def format_normalized_summary(normalized: NormalizedAnswers) -> str:
    lines = [
        "",
        "NORMALIZED INPUT",
        "----------------",
        f"health_priority_codes: {normalized.health_priority_codes!r}",
        f"diet_preference: {normalized.diet_preference!r}",
        f"food_groups: {normalized.food_groups!r}",
        f"fresh_fruit_frequency: {normalized.fresh_fruit_frequency!r}",
        f"fresh_vegetable_frequency: {normalized.fresh_vegetable_frequency!r}",
        f"healthy_breakfast_frequency: {normalized.healthy_breakfast_frequency!r}",
        f"baked_goods_frequency: {normalized.baked_goods_frequency!r}",
        f"dessert_frequency: {normalized.dessert_frequency!r}",
        f"water_intake_frequency: {normalized.water_intake_frequency!r}",
        f"extra_salt_frequency: {normalized.extra_salt_frequency!r}",
        f"gender: {normalized.gender!r}",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local interactive tester for the Nutrition Intelligence Engine.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Also print raw lookup, normalized answers, and intermediate engine objects.",
    )
    return parser.parse_args(argv)


def run_once(
    *,
    debug: bool,
    infile: TextIO | None = None,
    outfile: TextIO | None = None,
    config: NutritionEngineConfig | None = None,
) -> dict[str, Any]:
    infile = infile if infile is not None else sys.stdin
    outfile = outfile if outfile is not None else sys.stdout
    engine_config = config or load_nutrition_engine_config()
    catalog = build_questionnaire_catalog()
    reverse_map = build_option_reverse_map(catalog)
    lookup = collect_questionnaire_lookup(catalog, infile=infile, outfile=outfile)
    result = run_pipeline(
        lookup,
        config=engine_config,
        option_reverse_map=reverse_map,
    )
    outfile.write(format_normalized_summary(result["normalized"]))
    outfile.write("\n")
    outfile.write(format_user_result(result["user_result"], config=engine_config))
    if debug:
        outfile.write(format_result(result, config=engine_config))
        outfile.write(format_debug(result))
    outfile.flush()
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_nutrition_engine_config()
    while True:
        try:
            run_once(debug=args.debug, config=config)
        except EOFError:
            sys.stdout.write("\nInput closed. Exiting.\n")
            return 0
        except KeyboardInterrupt:
            sys.stdout.write("\nInterrupted. Exiting.\n")
            return 130

        try:
            again = _prompt_line(
                "\nRun another test? [y/n]: ",
                infile=sys.stdin,
                outfile=sys.stdout,
            )
        except EOFError:
            return 0
        if again.strip().lower() not in {"y", "yes"}:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
