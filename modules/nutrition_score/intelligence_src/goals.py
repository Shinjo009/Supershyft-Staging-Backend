"""Goal resolution, profiles, and combination for Nutrition Intelligence.

Consolidated from goal_resolver, goal_profiles, and combination modules.
Methodology unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from modules.nutrition_score.intelligence_src.config_loader import (
    NutritionEngineConfig,
    TargetDefinition,
    load_nutrition_engine_config,
)
from modules.nutrition_score.intelligence_src.models import (
    GOAL_IDS,
    PRIORITY_LEVELS,
    QUESTIONNAIRE_GOAL_CODE_TO_ID,
    CombinationRule,
    CombinedNutritionProfile,
    CompatibilityLevel,
    GoalId,
    GoalProfile,
    NormalizedAnswers,
    NutritionTargets,
    PriorityLevel,
    TargetRange,
)


# --- Goal Resolver ---

_MAX_GOALS = 2

def resolve_goals(answers: NormalizedAnswers) -> list[GoalId]:
    """Resolve stored health-priority option codes into GoalIds.

    Uses ``NormalizedAnswers.health_priority_codes`` only. Never infers goals
    from weight, diet, activity, demographics, or any other field.
    """
    return resolve_goal_codes(answers.health_priority_codes)

def resolve_goal_codes(codes: Sequence[str] | None) -> list[GoalId]:
    """Map 0–N questionnaire goal codes to up to two unique GoalIds.

    - Preserves first-occurrence order
    - Deduplicates
    - Ignores unknown codes
    - Caps at two valid unique goals
    - Returns ``[]`` when none are valid
    """
    if not codes:
        return []

    resolved: list[GoalId] = []
    seen: set[GoalId] = set()
    for raw in codes:
        if raw is None:
            continue
        code = str(raw).strip()
        if not code:
            continue
        goal_id = QUESTIONNAIRE_GOAL_CODE_TO_ID.get(code)
        if goal_id is None or goal_id in seen:
            continue
        seen.add(goal_id)
        resolved.append(goal_id)
        if len(resolved) >= _MAX_GOALS:
            break
    return resolved

# --- Goal Profiles ---

def load_goal_profiles(
    goal_ids: Sequence[GoalId | str] | None,
    *,
    config: NutritionEngineConfig | None = None,
) -> list[GoalProfile]:
    """Return GoalProfiles for resolved goal ids, preserving input order.

    - Zero goals → ``[]``
    - Unknown / invalid goal ids are skipped (same ignore philosophy as
      ``resolve_goal_codes``); definitions themselves remain YAML-only.
    - Returned profiles are detached copies so callers cannot mutate the
      loaded configuration dictionaries in-place.
    """
    if not goal_ids:
        return []

    engine_config = config or load_nutrition_engine_config()
    profiles: list[GoalProfile] = []
    for raw in goal_ids:
        if raw is None:
            continue
        goal_id = str(raw).strip()
        if goal_id not in GOAL_IDS:
            continue
        typed_id: GoalId = goal_id  # type: ignore[assignment]
        profile = engine_config.goals.get(typed_id)
        if profile is None:
            continue
        profiles.append(_detach_profile(profile))
    return profiles

def _detach_profile(profile: GoalProfile) -> GoalProfile:
    """Return a GoalProfile whose mutable mappings are independent copies."""
    return GoalProfile(
        id=profile.id,
        questionnaire_code=profile.questionnaire_code,
        display_name=profile.display_name,
        base_target_keys=profile.base_target_keys,
        priority_levels=dict(profile.priority_levels),
        food_quality_priorities=profile.food_quality_priorities,
        activity_dependencies=deepcopy(profile.activity_dependencies),
        conflict_tags=profile.conflict_tags,
        notes=profile.notes,
    )

# --- Goal Combination ---

_KNOWN_PRIORITY_RESOLUTIONS = frozenset({"max_of_shared", "weighted_blend"})

_KNOWN_TARGET_RESOLUTIONS = frozenset(
    {
        "overlap_or_widen",
        "overlap_higher_protein",
        "prefer_higher_protein",
        "prefer_activity_aware",
        "quality_focused",
        "prefer_higher",
        "prefer_adequate",
        "resolve_energy_conflict",
        "protein_priority_with_moderate_guidance",
    }
)

_FIBRE_RANK = {"moderate": 1, "high": 2}

_HYDRATION_RANK = {"standard": 1, "elevated": 2}

def combine_goal_profiles(
    profiles: Sequence[GoalProfile] | None,
    *,
    config: NutritionEngineConfig | None = None,
) -> CombinedNutritionProfile:
    """Combine 0–2 goal profiles into one CombinedNutritionProfile.

    - 0 goals → baseline/general profile from indicator general-quality priorities
    - 1 goal → detached combined representation of that profile
    - 2 goals → generic merge using combinations.yaml
    """
    engine_config = config or load_nutrition_engine_config()
    unique = _dedupe_profiles(profiles)

    if len(unique) == 0:
        return _combine_zero(engine_config)
    if len(unique) == 1:
        return _combine_one(unique[0])
    if len(unique) == 2:
        return _combine_two(unique[0], unique[1], engine_config)
    raise ValueError(
        f"Goal combination supports at most 2 goals; received {len(unique)}: "
        f"{[p.id for p in unique]}"
    )

def _dedupe_profiles(profiles: Sequence[GoalProfile] | None) -> list[GoalProfile]:
    if not profiles:
        return []
    out: list[GoalProfile] = []
    seen: set[GoalId] = set()
    for profile in profiles:
        if profile.id in seen:
            continue
        seen.add(profile.id)
        out.append(profile)
    return out

def _combine_zero(config: NutritionEngineConfig) -> CombinedNutritionProfile:
    priority_levels = {
        indicator_id: indicator.general_quality_priority
        for indicator_id, indicator in config.indicators.items()
    }
    return CombinedNutritionProfile(
        goals=(),
        compatibility=None,
        priority_levels=dict(priority_levels),
        target_keys=(),
        conflict_resolutions=(),
        notes=("zero_goal_baseline",),
        merged_targets=NutritionTargets(notes=("zero_goal_baseline",)),
        priority_resolution=None,
        target_resolution_applied={},
        conflict_severity=None,
        food_quality_priorities=(),
        activity_dependencies={},
    )

def _combine_one(profile: GoalProfile) -> CombinedNutritionProfile:
    return CombinedNutritionProfile(
        goals=(profile.id,),
        compatibility=None,
        priority_levels=dict(profile.priority_levels),
        target_keys=tuple(profile.base_target_keys),
        conflict_resolutions=(),
        notes=("single_goal",) + tuple(profile.notes),
        merged_targets=None,
        priority_resolution=None,
        target_resolution_applied={},
        conflict_severity=None,
        food_quality_priorities=tuple(profile.food_quality_priorities),
        activity_dependencies=deepcopy(profile.activity_dependencies),
    )

def _combine_two(
    profile_a: GoalProfile,
    profile_b: GoalProfile,
    config: NutritionEngineConfig,
) -> CombinedNutritionProfile:
    rule = _resolve_pair_rule(profile_a, profile_b, config)
    target_resolution = {
        **config.combination_defaults.target_resolution,
        **rule.target_resolution,
    }
    # Tag-rule overlays (deterministic order of tag_rules as loaded).
    tag_notes: list[str] = []
    for tag_rule in config.combination_tag_rules:
        if _tag_rule_matches(tag_rule, profile_a, profile_b):
            overlay = tag_rule.get("target_resolution") or {}
            if isinstance(overlay, dict):
                target_resolution.update({str(k): str(v) for k, v in overlay.items()})
            for note in tag_rule.get("notes") or []:
                tag_notes.append(str(note))

    priority_resolution = rule.priority_resolution or config.combination_defaults.priority_resolution
    if priority_resolution not in _KNOWN_PRIORITY_RESOLUTIONS:
        raise ValueError(f"Unknown priority_resolution strategy: {priority_resolution!r}")

    for kind, strategy in target_resolution.items():
        if strategy not in _KNOWN_TARGET_RESOLUTIONS:
            raise ValueError(
                f"Unknown target_resolution strategy {strategy!r} for kind {kind!r}"
            )

    priority_levels = _merge_priority_levels(
        profile_a.priority_levels,
        profile_b.priority_levels,
        strategy=priority_resolution,
        level_weights=config.scoring.priority_level_weights,
    )

    merged_targets, selected_keys, applied, conflict_bits = _merge_targets(
        profile_a,
        profile_b,
        target_resolution=target_resolution,
        config=config,
    )

    food_quality = _merge_food_quality(profile_a, profile_b)
    activity_deps = _merge_activity_dependencies(profile_a, profile_b)

    notes = list(rule.notes) + tag_notes
    notes.append(f"pair_rule:{rule.goal_a}+{rule.goal_b}")
    notes.append(f"priority_resolution:{priority_resolution}")
    for kind, strategy in sorted(applied.items()):
        notes.append(f"target_resolution:{kind}={strategy}")

    return CombinedNutritionProfile(
        goals=(profile_a.id, profile_b.id),
        compatibility=rule.compatibility,
        priority_levels=priority_levels,
        target_keys=tuple(selected_keys),
        conflict_resolutions=tuple(conflict_bits),
        notes=tuple(notes),
        merged_targets=merged_targets,
        priority_resolution=priority_resolution,
        target_resolution_applied=dict(applied),
        conflict_severity=rule.conflict_severity or config.combination_defaults.conflict_severity,
        food_quality_priorities=food_quality,
        activity_dependencies=activity_deps,
    )

def _resolve_pair_rule(
    profile_a: GoalProfile,
    profile_b: GoalProfile,
    config: NutritionEngineConfig,
) -> CombinationRule:
    key = tuple(sorted((profile_a.id, profile_b.id)))
    for rule in config.combination_pairs:
        if (rule.goal_a, rule.goal_b) == key:
            return rule
    raise ValueError(
        f"Missing combination rule for goals {key!r}. "
        "Add the pair to combinations.yaml; refusing to invent a strategy."
    )

def _tag_rule_matches(tag_rule: dict[str, Any], a: GoalProfile, b: GoalProfile) -> bool:
    tags = set(a.conflict_tags) | set(b.conflict_tags)
    both = tag_rule.get("when_both_tags") or []
    any_tags = tag_rule.get("when_any_tag") or []
    if both:
        needed = {str(t) for t in both}
        # Require one tag on each profile when both tags are listed as a pair conflict.
        if len(needed) == 2:
            t1, t2 = tuple(needed)
            a_tags = set(a.conflict_tags)
            b_tags = set(b.conflict_tags)
            crossed = (t1 in a_tags and t2 in b_tags) or (t2 in a_tags and t1 in b_tags)
            if not crossed:
                return False
        elif not needed.issubset(tags):
            return False
    if any_tags and not ({str(t) for t in any_tags} & tags):
        return False
    if not both and not any_tags:
        return False
    return True

def _merge_priority_levels(
    a: dict[str, PriorityLevel],
    b: dict[str, PriorityLevel],
    *,
    strategy: str,
    level_weights: dict[PriorityLevel, float],
) -> dict[str, PriorityLevel]:
    keys = sorted(set(a) | set(b))
    merged: dict[str, PriorityLevel] = {}
    for key in keys:
        left = a.get(key)
        right = b.get(key)
        if left is None and right is None:
            continue
        if left is None:
            merged[key] = right  # type: ignore[assignment]
            continue
        if right is None:
            merged[key] = left
            continue
        if strategy == "max_of_shared":
            merged[key] = _max_priority(left, right, level_weights)
        elif strategy == "weighted_blend":
            merged[key] = _blend_priority(left, right, level_weights)
        else:
            raise ValueError(f"Unknown priority_resolution strategy: {strategy!r}")
    return merged

def _max_priority(
    left: PriorityLevel,
    right: PriorityLevel,
    weights: dict[PriorityLevel, float],
) -> PriorityLevel:
    return left if weights[left] >= weights[right] else right

def _blend_priority(
    left: PriorityLevel,
    right: PriorityLevel,
    weights: dict[PriorityLevel, float],
) -> PriorityLevel:
    avg = (weights[left] + weights[right]) / 2.0
    # Nearest level by absolute distance; ties → higher weight (deterministic).
    best: PriorityLevel | None = None
    best_dist = float("inf")
    best_weight = float("-inf")
    for level in PRIORITY_LEVELS:
        dist = abs(weights[level] - avg)
        w = weights[level]
        if dist < best_dist or (dist == best_dist and w > best_weight):
            best = level
            best_dist = dist
            best_weight = w
    assert best is not None
    return best

def _targets_by_kind(
    profile: GoalProfile,
    config: NutritionEngineConfig,
) -> dict[str, tuple[str, TargetDefinition]]:
    out: dict[str, tuple[str, TargetDefinition]] = {}
    for key in profile.base_target_keys:
        definition = config.targets.get(key)
        if definition is None:
            raise ValueError(f"Goal {profile.id} references unknown target key {key!r}")
        # First key wins per kind within a single goal (goals define one per kind).
        out.setdefault(definition.kind, (key, definition))
    return out

def _merge_targets(
    profile_a: GoalProfile,
    profile_b: GoalProfile,
    *,
    target_resolution: dict[str, str],
    config: NutritionEngineConfig,
) -> tuple[NutritionTargets, list[str], dict[str, str], list[str]]:
    by_a = _targets_by_kind(profile_a, config)
    by_b = _targets_by_kind(profile_b, config)
    kinds = sorted(set(by_a) | set(by_b) | set(target_resolution))

    protein_range: TargetRange | None = None
    carb_range: TargetRange | None = None
    fibre_priority: str | None = None
    hydration_priority: str | None = None
    energy_concept: str | None = None
    selected_keys: list[str] = []
    applied: dict[str, str] = {}
    conflicts: list[str] = []
    target_notes: list[str] = []

    for kind in kinds:
        left = by_a.get(kind)
        right = by_b.get(kind)
        strategy = target_resolution.get(kind)
        if strategy is None:
            # No configured strategy: keep single-side target if only one present.
            if left and not right:
                selected_keys.append(left[0])
                protein_range, carb_range, fibre_priority, hydration_priority, energy_concept = (
                    _apply_single_definition(
                        left[1],
                        protein_range,
                        carb_range,
                        fibre_priority,
                        hydration_priority,
                        energy_concept,
                    )
                )
            elif right and not left:
                selected_keys.append(right[0])
                protein_range, carb_range, fibre_priority, hydration_priority, energy_concept = (
                    _apply_single_definition(
                        right[1],
                        protein_range,
                        carb_range,
                        fibre_priority,
                        hydration_priority,
                        energy_concept,
                    )
                )
            elif left and right:
                raise ValueError(
                    f"No target_resolution strategy configured for kind {kind!r} "
                    f"with both goals defining it"
                )
            continue

        applied[kind] = strategy
        if left is None and right is None:
            continue
        if left is None:
            selected_keys.append(right[0])  # type: ignore[index]
            protein_range, carb_range, fibre_priority, hydration_priority, energy_concept = (
                _apply_single_definition(
                    right[1],  # type: ignore[index]
                    protein_range,
                    carb_range,
                    fibre_priority,
                    hydration_priority,
                    energy_concept,
                )
            )
            continue
        if right is None:
            selected_keys.append(left[0])
            protein_range, carb_range, fibre_priority, hydration_priority, energy_concept = (
                _apply_single_definition(
                    left[1],
                    protein_range,
                    carb_range,
                    fibre_priority,
                    hydration_priority,
                    energy_concept,
                )
            )
            continue

        key_a, def_a = left
        key_b, def_b = right
        chosen_key, chosen_def, conflict = _resolve_target_pair(def_a, def_b, key_a, key_b, strategy)
        if conflict:
            conflicts.append(conflict)
            target_notes.append(conflict)
        selected_keys.append(chosen_key)
        # For numeric kinds, store resolved range from strategy (may differ from chosen_def.range).
        if kind == "protein_g_per_kg":
            protein_range = chosen_def.range
        elif kind == "carbohydrate_g_per_kg":
            carb_range = chosen_def.range
        elif kind == "fibre_priority":
            fibre_priority = chosen_def.priority
        elif kind == "hydration_priority":
            hydration_priority = chosen_def.priority
        elif kind == "energy_concept":
            energy_concept = chosen_def.concept

    # Deduplicate selected keys while preserving order.
    deduped_keys: list[str] = []
    seen_keys: set[str] = set()
    for key in selected_keys:
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped_keys.append(key)

    return (
        NutritionTargets(
            protein_g_per_kg=protein_range,
            carbohydrate_g_per_kg=carb_range,
            fibre_priority=fibre_priority,
            hydration_priority=hydration_priority,
            energy_concept=energy_concept,
            notes=tuple(target_notes),
        ),
        deduped_keys,
        applied,
        conflicts,
    )

def _apply_single_definition(
    definition: TargetDefinition,
    protein_range: TargetRange | None,
    carb_range: TargetRange | None,
    fibre_priority: str | None,
    hydration_priority: str | None,
    energy_concept: str | None,
) -> tuple[TargetRange | None, TargetRange | None, str | None, str | None, str | None]:
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
    return protein_range, carb_range, fibre_priority, hydration_priority, energy_concept

def _resolve_target_pair(
    def_a: TargetDefinition,
    def_b: TargetDefinition,
    key_a: str,
    key_b: str,
    strategy: str,
) -> tuple[str, TargetDefinition, str | None]:
    """Return (selected_key, effective_definition, optional_conflict_note)."""
    if strategy == "overlap_or_widen":
        return _resolve_overlap_or_widen(def_a, def_b, key_a, key_b)
    if strategy == "overlap_higher_protein":
        return _resolve_overlap_higher_protein(def_a, def_b, key_a, key_b)
    if strategy == "prefer_higher_protein":
        return _prefer_higher_protein(def_a, def_b, key_a, key_b)
    if strategy == "prefer_activity_aware":
        return _prefer_mode(def_a, def_b, key_a, key_b, preferred_mode="activity_dependent")
    if strategy == "quality_focused":
        return _prefer_mode(def_a, def_b, key_a, key_b, preferred_mode="quality_focused")
    if strategy == "prefer_higher":
        return _prefer_higher_categorical(def_a, def_b, key_a, key_b)
    if strategy == "prefer_adequate":
        return _prefer_energy_concept(def_a, def_b, key_a, key_b, prefer="adequate")
    if strategy == "resolve_energy_conflict":
        return _resolve_energy_conflict(def_a, def_b, key_a, key_b)
    if strategy == "protein_priority_with_moderate_guidance":
        return _energy_guidance_concept(def_a, def_b, key_a, key_b)
    raise ValueError(f"Unknown target_resolution strategy: {strategy!r}")

def _with_range(definition: TargetDefinition, range_: TargetRange) -> TargetDefinition:
    return TargetDefinition(
        key=definition.key,
        kind=definition.kind,
        range=range_,
        priority=definition.priority,
        concept=definition.concept,
        activity_bands=definition.activity_bands,
        notes=definition.notes,
    )

def _with_concept(definition: TargetDefinition, concept: str) -> TargetDefinition:
    return TargetDefinition(
        key=definition.key,
        kind=definition.kind,
        range=definition.range,
        priority=definition.priority,
        concept=concept,
        activity_bands=definition.activity_bands,
        notes=definition.notes,
    )

def _overlap_range(a: TargetRange, b: TargetRange) -> TargetRange | None:
    if a.low is None or a.high is None or b.low is None or b.high is None:
        return None
    low = max(a.low, b.low)
    high = min(a.high, b.high)
    if low <= high:
        return TargetRange(
            low=low,
            high=high,
            unit=a.unit or b.unit,
            mode=a.mode or b.mode,
        )
    return None

def _widen_range(a: TargetRange, b: TargetRange) -> TargetRange:
    assert a.low is not None and a.high is not None and b.low is not None and b.high is not None
    return TargetRange(
        low=min(a.low, b.low),
        high=max(a.high, b.high),
        unit=a.unit or b.unit,
        mode=a.mode or b.mode,
    )

def _range_midpoint(range_: TargetRange) -> float:
    assert range_.low is not None and range_.high is not None
    return (range_.low + range_.high) / 2.0

def _resolve_overlap_or_widen(
    def_a: TargetDefinition,
    def_b: TargetDefinition,
    key_a: str,
    key_b: str,
) -> tuple[str, TargetDefinition, str | None]:
    if def_a.range is None or def_b.range is None:
        return key_a, def_a, None
    overlap = _overlap_range(def_a.range, def_b.range)
    if overlap is not None:
        return key_a, _with_range(def_a, overlap), None
    widened = _widen_range(def_a.range, def_b.range)
    return key_a, _with_range(def_a, widened), f"overlap_or_widen:widened:{key_a}+{key_b}"

def _resolve_overlap_higher_protein(
    def_a: TargetDefinition,
    def_b: TargetDefinition,
    key_a: str,
    key_b: str,
) -> tuple[str, TargetDefinition, str | None]:
    if def_a.range is None or def_b.range is None:
        return _prefer_higher_protein(def_a, def_b, key_a, key_b)
    overlap = _overlap_range(def_a.range, def_b.range)
    if overlap is not None:
        return key_a, _with_range(def_a, overlap), None
    return _prefer_higher_protein(def_a, def_b, key_a, key_b)

def _prefer_higher_protein(
    def_a: TargetDefinition,
    def_b: TargetDefinition,
    key_a: str,
    key_b: str,
) -> tuple[str, TargetDefinition, str | None]:
    if def_a.range is None and def_b.range is None:
        return key_a, def_a, None
    if def_a.range is None:
        return key_b, def_b, None
    if def_b.range is None:
        return key_a, def_a, None
    mid_a = _range_midpoint(def_a.range)
    mid_b = _range_midpoint(def_b.range)
    if mid_b > mid_a:
        return key_b, def_b, None
    if mid_a > mid_b:
        return key_a, def_a, None
    # Tie: prefer higher high, then key_a for determinism.
    high_a = def_a.range.high if def_a.range.high is not None else float("-inf")
    high_b = def_b.range.high if def_b.range.high is not None else float("-inf")
    if high_b > high_a:
        return key_b, def_b, None
    return key_a, def_a, None

def _prefer_mode(
    def_a: TargetDefinition,
    def_b: TargetDefinition,
    key_a: str,
    key_b: str,
    *,
    preferred_mode: str,
) -> tuple[str, TargetDefinition, str | None]:
    mode_a = def_a.range.mode if def_a.range else None
    mode_b = def_b.range.mode if def_b.range else None
    if mode_a == preferred_mode and mode_b != preferred_mode:
        return key_a, def_a, None
    if mode_b == preferred_mode and mode_a != preferred_mode:
        return key_b, def_b, None
    if mode_a == preferred_mode and mode_b == preferred_mode:
        return key_a, def_a, None
    # Neither matches: keep first goal's definition (deterministic, no invention).
    return key_a, def_a, f"prefer_mode:{preferred_mode}:fallback:{key_a}"

def _prefer_higher_categorical(
    def_a: TargetDefinition,
    def_b: TargetDefinition,
    key_a: str,
    key_b: str,
) -> tuple[str, TargetDefinition, str | None]:
    if def_a.kind == "fibre_priority":
        rank = _FIBRE_RANK
    elif def_a.kind == "hydration_priority":
        rank = _HYDRATION_RANK
    else:
        raise ValueError(f"prefer_higher is not defined for kind {def_a.kind!r}")
    ra = rank.get(str(def_a.priority or ""), 0)
    rb = rank.get(str(def_b.priority or ""), 0)
    if rb > ra:
        return key_b, def_b, None
    return key_a, def_a, None

def _prefer_energy_concept(
    def_a: TargetDefinition,
    def_b: TargetDefinition,
    key_a: str,
    key_b: str,
    *,
    prefer: str,
) -> tuple[str, TargetDefinition, str | None]:
    if def_a.concept == prefer:
        return key_a, def_a, None
    if def_b.concept == prefer:
        return key_b, def_b, None
    return key_a, def_a, f"prefer_{prefer}:fallback:{key_a}"

def _resolve_energy_conflict(
    def_a: TargetDefinition,
    def_b: TargetDefinition,
    key_a: str,
    key_b: str,
) -> tuple[str, TargetDefinition, str | None]:
    if def_a.concept == def_b.concept:
        return key_a, def_a, None
    concepts = {def_a.concept, def_b.concept}
    if concepts == {"deficit", "adequate"} or concepts == {"deficit", "none"} or concepts == {
        "adequate",
        "none",
    }:
        # Configured conflict resolution label (not a measured energy value).
        return (
            key_a,
            _with_concept(def_a, "protein_priority_with_moderate_guidance"),
            f"resolve_energy_conflict:{def_a.concept}+{def_b.concept}",
        )
    return key_a, def_a, f"resolve_energy_conflict:unhandled:{def_a.concept}+{def_b.concept}"

def _energy_guidance_concept(
    def_a: TargetDefinition,
    def_b: TargetDefinition,
    key_a: str,
    key_b: str,
) -> tuple[str, TargetDefinition, str | None]:
    return (
        key_a,
        _with_concept(def_a, "protein_priority_with_moderate_guidance"),
        f"protein_priority_with_moderate_guidance:{def_a.concept}+{def_b.concept}",
    )

def _merge_food_quality(a: GoalProfile, b: GoalProfile) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for item in list(a.food_quality_priorities) + list(b.food_quality_priorities):
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return tuple(out)

def _merge_activity_dependencies(a: GoalProfile, b: GoalProfile) -> dict[str, object]:
    merged: dict[str, object] = {}
    merged.update(deepcopy(a.activity_dependencies))
    # Later profile overlays same keys (deterministic: profile_b wins on key clash).
    merged.update(deepcopy(b.activity_dependencies))
    return merged
