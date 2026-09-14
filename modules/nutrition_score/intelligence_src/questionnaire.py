"""Input Normalizer for the Nutrition Intelligence Engine.

Converts raw questionnaire lookup answers into canonical option codes and
scale values. Does not score, interpret healthiness, invent goals, or
fabricate intake/targets.

Choice/label resolution matches ReportsService helpers (copied here so the
engine does not import the full reports stack). Health-priority maps come from
questionnaire_field_config rather than inventing new option mappings.
"""

from __future__ import annotations

import re
from typing import Any

from modules.nutrition_score.intelligence_src.health_priorities import (
    HEALTH_PRIORITIES_LABEL_TO_VALUE,
    HEALTH_PRIORITIES_OPTION_VALUES,
)
from modules.nutrition_score.intelligence_src.models import NormalizedAnswers, ScaleValue

# Copied from ReportsService._VEGETARIAN_DIET_PREFERENCE_VALUES — do not "fix".
_VEGETARIAN_DIET_PREFERENCE_VALUES = frozenset({"0", "3", "4", "5"})

# Single-choice fields normalized to option_value codes when present.
_SINGLE_CHOICE_FIELDS: tuple[str, ...] = (
    "diet_preference",
    "healthy_breakfast_frequency",
    "fresh_fruit_frequency",
    "fresh_vegetable_frequency",
    "baked_goods_frequency",
    "dessert_frequency",
    "butter_dish_frequency",
    "red_meat_frequency",
    "extra_salt_frequency",
    "iodized_salt_status",
    "caffeine_frequency",
    "water_intake_frequency",
    "sickness_frequency",
    "exercise_frequency_week",
    "exercise_level",
    "physical_activity_frequency",
    "daily_active_duration",
    "sleeping_hours",
    "alcohol_frequency",
    "tobacco_frequency",
    "goal_preference",
)

_MULTI_CHOICE_FIELDS: tuple[str, ...] = (
    "food_groups",
    "caffeine_type",
)

_MAX_HEALTH_PRIORITIES = 2


def normalize_questionnaire_lookup(
    lookup: dict[str, Any],
    *,
    user_gender: str | None = None,
    option_reverse_map: dict[str, dict[str, str]] | None = None,
) -> NormalizedAnswers:
    """Normalize a ReportsService-style questionnaire lookup.

    Parameters
    ----------
    lookup:
        ``question_key -> answer`` mapping as produced by
        ``ReportsService._build_questionnaire_lookup``.
    user_gender:
        Optional profile gender fallback (same as Health Span Index).
    option_reverse_map:
        Optional ``{question_key: {label_or_code_or_fingerprint: option_value}}``
        as built by ``ReportsService._build_option_reverse_map``.
    """
    reverse_map = option_reverse_map or {}

    single_choices: dict[str, str | None] = {}
    for key in _SINGLE_CHOICE_FIELDS:
        single_choices[key] = _normalize_optional_choice(
            lookup.get(key),
            reverse_map.get(key, {}),
        )

    multi_choices: dict[str, tuple[str, ...] | None] = {}
    for key in _MULTI_CHOICE_FIELDS:
        multi_choices[key] = _normalize_optional_multi_choice(
            lookup.get(key),
            reverse_map.get(key, {}),
            present=(key in lookup),
        )

    health_priority_codes = _normalize_health_priorities(
        lookup.get("health_priorities") if "health_priorities" in lookup else None,
        reverse_map.get("health_priorities", {}),
    )

    diet_preference = single_choices["diet_preference"]
    red_meat = single_choices["red_meat_frequency"]
    red_meat_defaulted = False
    if red_meat is None and diet_preference in _VEGETARIAN_DIET_PREFERENCE_VALUES:
        # Preserve existing ReportsService nutrition-payload fallback.
        red_meat = "5"
        red_meat_defaulted = True

    gender = _normalize_gender(lookup.get("gender")) or _normalize_gender(user_gender)

    age = _normalize_age(lookup.get("age") if "age" in lookup else None)
    height = _normalize_height(lookup.get("height") if "height" in lookup else None)
    weight = _normalize_weight(lookup.get("weight") if "weight" in lookup else None)
    waist_circumference = _normalize_waist(
        lookup.get("waist_circumference")
        if "waist_circumference" in lookup
        else None
    )
    waist_input_unit = _waist_input_unit(
        lookup.get("waist_circumference")
        if "waist_circumference" in lookup
        else None
    )
    body_fat_percent = _normalize_body_fat(
        lookup.get("body_fat") if "body_fat" in lookup else None
    )
    weight_loss_goal = _normalize_weight_loss_goal(
        lookup.get("weight_loss_goal") if "weight_loss_goal" in lookup else None
    )

    return NormalizedAnswers(
        health_priority_codes=health_priority_codes,
        gender=gender,
        age=age,
        height=height,
        weight=weight,
        waist_circumference=waist_circumference,
        waist_input_unit=waist_input_unit,
        body_fat_percent=body_fat_percent,
        diet_preference=diet_preference,
        food_groups=multi_choices["food_groups"],
        healthy_breakfast_frequency=single_choices["healthy_breakfast_frequency"],
        fresh_fruit_frequency=single_choices["fresh_fruit_frequency"],
        fresh_vegetable_frequency=single_choices["fresh_vegetable_frequency"],
        baked_goods_frequency=single_choices["baked_goods_frequency"],
        dessert_frequency=single_choices["dessert_frequency"],
        butter_dish_frequency=single_choices["butter_dish_frequency"],
        red_meat_frequency=red_meat,
        red_meat_frequency_defaulted=red_meat_defaulted,
        extra_salt_frequency=single_choices["extra_salt_frequency"],
        iodized_salt_status=single_choices["iodized_salt_status"],
        caffeine_frequency=single_choices["caffeine_frequency"],
        caffeine_type=multi_choices["caffeine_type"],
        water_intake_frequency=single_choices["water_intake_frequency"],
        sickness_frequency=single_choices["sickness_frequency"],
        exercise_frequency_week=single_choices["exercise_frequency_week"],
        exercise_level=single_choices["exercise_level"],
        physical_activity_frequency=single_choices["physical_activity_frequency"],
        daily_active_duration=single_choices["daily_active_duration"],
        sleeping_hours=single_choices["sleeping_hours"],
        alcohol_frequency=single_choices["alcohol_frequency"],
        tobacco_frequency=single_choices["tobacco_frequency"],
        goal_preference=single_choices["goal_preference"],
        weight_loss_goal=weight_loss_goal,
    )


def _normalize_optional_choice(raw: Any, key_map: dict[str, str]) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        # Unexpected list for single_choice: take first resolvable item only.
        for item in raw:
            resolved = _resolve_choice_code(item, key_map)
            if resolved is not None:
                return resolved
        return None
    return _resolve_choice_code(raw, key_map)


def _normalize_optional_multi_choice(
    raw: Any,
    key_map: dict[str, str],
    *,
    present: bool,
) -> tuple[str, ...] | None:
    if not present:
        return None
    if raw is None:
        return None
    if isinstance(raw, list):
        items = raw
    else:
        items = [raw]
    resolved: list[str] = []
    seen: set[str] = set()
    for item in items:
        code = _resolve_choice_code(item, key_map)
        if code is None or code in seen:
            continue
        seen.add(code)
        resolved.append(code)
    return tuple(resolved)


def _resolve_choice_code(raw: Any, key_map: dict[str, str]) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    resolved = _resolve_nutrition_choice_value(raw, key_map)
    resolved_text = str(resolved).strip() if resolved is not None else ""
    return resolved_text or None


def _normalize_health_priorities(raw: Any, key_map: dict[str, str]) -> tuple[str, ...]:
    """Return 0–2 canonical health_priorities option codes. Never invent goals."""
    if raw is None:
        return ()

    if isinstance(raw, list):
        fragments = raw
    else:
        fragments = [raw]

    codes: list[str] = []
    seen: set[str] = set()
    for fragment in fragments:
        code = _resolve_health_priority_code(fragment, key_map)
        if code is None or code in seen:
            continue
        seen.add(code)
        codes.append(code)
        if len(codes) >= _MAX_HEALTH_PRIORITIES:
            break
    return tuple(codes)


def _resolve_health_priority_code(raw: Any, key_map: dict[str, str]) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() == "none":
        return None

    if key_map:
        via_map = _resolve_nutrition_choice_value(raw, key_map)
        via_text = str(via_map).strip() if via_map is not None else ""
        if via_text in HEALTH_PRIORITIES_OPTION_VALUES:
            return via_text

    # Existing questionnaire_field_config code/label maps (same source Metsights uses).
    if text in HEALTH_PRIORITIES_OPTION_VALUES:
        return text

    normalized = _normalize_choice_label(text)
    by_label = HEALTH_PRIORITIES_LABEL_TO_VALUE.get(normalized)
    if by_label is not None:
        return by_label

    fingerprint = _choice_fingerprint(text)
    for label, code in HEALTH_PRIORITIES_LABEL_TO_VALUE.items():
        if _choice_fingerprint(label) == fingerprint:
            return code

    return None


def _normalize_height(raw: Any) -> ScaleValue | None:
    if raw is None:
        return None
    value, unit = _extract_scale_answer(raw)
    normalized_unit = _normalize_height_unit(unit)
    if value is None and normalized_unit is None and unit is None:
        # Present but unparseable → still surface empty scale rather than inventing.
        if isinstance(raw, dict):
            return ScaleValue(value=None, unit=None)
        return None
    return ScaleValue(value=value, unit=normalized_unit)


def _normalize_weight(raw: Any) -> ScaleValue | None:
    if raw is None:
        return None
    value, unit = _extract_scale_answer(raw)
    normalized_unit = _normalize_weight_unit(unit)
    if value is None and normalized_unit is None and not isinstance(raw, dict):
        return None
    if isinstance(raw, dict):
        return ScaleValue(value=value, unit=normalized_unit)
    return None


def _normalize_weight_loss_goal(raw: Any) -> ScaleValue | None:
    # Same scale shape as weight; reuse weight-unit codes (kg/lb).
    return _normalize_weight(raw)


def _normalize_age(raw: Any) -> int | None:
    """Accept positive integers only; never truncate floats."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, str):
        text = raw.strip()
        if not re.fullmatch(r"[0-9]+", text):
            return None
        value = int(text)
        return value if value > 0 else None
    return None


def _normalize_waist(raw: Any) -> ScaleValue | None:
    """Normalize questionnaire waist circumference to centimetres."""
    if raw is None:
        return None
    value, unit = _extract_scale_answer(raw)
    if value is None or float(value) <= 0:
        return None
    normalized_unit = _normalize_waist_unit(unit)
    if normalized_unit is None:
        return None
    numeric = float(value)
    cm = _waist_to_cm(numeric, normalized_unit)
    return ScaleValue(value=cm, unit="cm")


def _waist_input_unit(raw: Any) -> str | None:
    if not isinstance(raw, dict) or raw.get("value") is None:
        return None
    return _normalize_waist_unit(raw.get("unit"))


def _normalize_waist_unit(unit: Any) -> str | None:
    normalized = str(unit or "cm").strip().lower()
    if normalized in {"0", "cm"}:
        return "cm"
    if normalized in {"1", "in", "inch", "inches"}:
        return "in"
    return None


def _waist_to_cm(value: float, unit: str) -> float:
    """Convert once to the canonical calculation unit without display rounding."""
    return value if unit == "cm" else value * 2.54


def _normalize_body_fat(raw: Any) -> float | None:
    """Normalize the current questionnaire body-fat percentage."""
    if raw is None or isinstance(raw, bool):
        return None
    value: Any = raw
    if isinstance(raw, dict):
        value = raw.get("value")
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0 or parsed > 100:
        return None
    return parsed


def _normalize_weight_unit(value: str | None) -> str | None:
    """Mirror ReportsService height-unit normalization for weight option codes."""
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"0", "kg"}:
        return "kg"
    if normalized in {"1", "lb", "lbs"}:
        return "lb"
    return value.strip() or None


def _normalize_gender(value: Any) -> str | None:
    """Identical to ReportsService._normalize_gender."""
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"m", "male"}:
        return "male"
    if normalized in {"f", "female"}:
        return "female"
    return normalized or None


def _extract_scale_answer(answer: Any) -> tuple[float | int | None, str | None]:
    """Identical to ReportsService._extract_scale_answer."""
    if not isinstance(answer, dict):
        return None, None
    raw_value = answer.get("value")
    raw_unit = answer.get("unit")
    if raw_value is None:
        return None, str(raw_unit).strip() if raw_unit is not None and str(raw_unit).strip() else None
    if isinstance(raw_value, bool):
        return None, None
    parsed_value: float | int | None = None
    try:
        parsed_numeric = float(raw_value)
        parsed_value = int(parsed_numeric) if parsed_numeric.is_integer() else parsed_numeric
    except (TypeError, ValueError):
        parsed_value = None
    parsed_unit = str(raw_unit).strip() if raw_unit is not None and str(raw_unit).strip() else None
    return parsed_value, parsed_unit


def _normalize_height_unit(value: str | None) -> str | None:
    """Identical to ReportsService._normalize_height_unit."""
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"0", "cm"}:
        return "cm"
    if normalized in {"2", "ft/in", "ft", "feet"}:
        return "ft/in"
    return value.strip() or None


def _normalize_choice_label(value: str) -> str:
    """Identical to ReportsService._normalize_choice_label."""
    text = (value or "").strip().lower()
    text = text.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text)


def _choice_fingerprint(value: str) -> str:
    """Identical to ReportsService._choice_fingerprint."""
    return re.sub(r"[^a-z0-9]+", "", _normalize_choice_label(value))


def _resolve_nutrition_choice_value(raw: Any, key_map: dict[str, str]) -> str:
    """Identical to ReportsService._resolve_nutrition_choice_value."""
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return text
    if text in key_map:
        return key_map[text]

    fingerprint = _choice_fingerprint(text)
    if fingerprint and fingerprint in key_map:
        return key_map[fingerprint]

    normalized = _normalize_choice_label(text)
    best: str | None = None
    best_score = -1
    for key, option_value in key_map.items():
        key_fp = _choice_fingerprint(key)
        if not key_fp:
            continue
        if fingerprint and (key_fp in fingerprint or fingerprint in key_fp):
            score = min(len(key_fp), len(fingerprint))
            if score > best_score:
                best = option_value
                best_score = score
                continue
        key_norm = _normalize_choice_label(key)
        if key_norm and (key_norm in normalized or normalized in key_norm):
            score = min(len(key_norm), len(normalized))
            if score > best_score:
                best = option_value
                best_score = score
    return best if best is not None else text
