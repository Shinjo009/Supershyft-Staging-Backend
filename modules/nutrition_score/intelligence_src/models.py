"""Internal data models for the Nutrition Intelligence Engine.

Phase 1 models only. No scoring logic, no I/O, no FastAPI/SQLAlchemy.

Conventions:
- Higher ``nutrition_score`` = better nutrition *behaviour* quality.
- Targets (g/kg, hydration priority, etc.) are never measured intake.
- Indicators are behavioural proxies derived from questionnaire answers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

GoalId = Literal[
    "weight_loss",
    "muscle_gain",
    "energy_levels",
    "metabolic_health",
    "endurance",
    "strength",
]

GOAL_IDS: tuple[GoalId, ...] = (
    "weight_loss",
    "muscle_gain",
    "energy_levels",
    "metabolic_health",
    "endurance",
    "strength",
)

# Questionnaire ``health_priorities`` option_value → GoalId
QUESTIONNAIRE_GOAL_CODE_TO_ID: dict[str, GoalId] = {
    "0": "weight_loss",
    "1": "muscle_gain",
    "2": "metabolic_health",
    "3": "energy_levels",
    "4": "strength",
    "5": "endurance",
}

PriorityLevel = Literal["very_high", "high", "medium", "low", "none"]

PRIORITY_LEVELS: tuple[PriorityLevel, ...] = (
    "very_high",
    "high",
    "medium",
    "low",
    "none",
)

ScoreDirection = Literal["higher_better", "lower_better"]

CompatibilityLevel = Literal["high", "moderate", "low"]

ZeroGoalMode = Literal["renormalize_quality_only", "use_neutral_alignment"]

MissingIndicatorPolicy = Literal["exclude_and_renormalize", "treat_as_neutral"]


@dataclass(frozen=True)
class TargetRange:
    """A target range (what the user should aim for), NOT measured intake."""

    low: float | None = None
    high: float | None = None
    unit: str | None = None
    mode: str | None = None


@dataclass(frozen=True)
class GoalProfile:
    """Configuration-backed profile for one nutrition/activity goal."""

    id: GoalId
    questionnaire_code: str
    display_name: str
    base_target_keys: tuple[str, ...] = ()
    priority_levels: dict[str, PriorityLevel] = field(default_factory=dict)
    food_quality_priorities: tuple[str, ...] = ()
    activity_dependencies: dict[str, object] = field(default_factory=dict)
    conflict_tags: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class IndicatorDefinition:
    """One observable behavioural proxy used for scoring.

    Scores reflect questionnaire behaviour quality, not nutrient adequacy.
    """

    id: str
    display_name: str
    source_fields: tuple[str, ...]
    score_direction: ScoreDirection
    general_quality_priority: PriorityLevel
    goal_relevance: dict[GoalId, PriorityLevel]
    description: str
    is_behavioural_proxy: bool = True
    uses_diet_preference_context: bool = False
    ordinal_scores: dict[str, float] = field(default_factory=dict)
    # Optional multi-select helpers from indicators.yaml (Phase 7).
    quality_group_codes: tuple[str, ...] = ()
    protein_supporting_group_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoreBand:
    """Configurable label band for a 0–100 score (higher = better)."""

    min_score: float
    label: str


@dataclass(frozen=True)
class ScoringConfig:
    """Score blend and band configuration (all values from YAML)."""

    general_quality_weight: float
    goal_alignment_weight: float
    zero_goal_mode: ZeroGoalMode
    missing_indicator_policy: MissingIndicatorPolicy
    priority_level_weights: dict[PriorityLevel, float]
    goal_critical_weight: float
    goal_supporting_weight: float
    score_bands: tuple[ScoreBand, ...]
    neutral_alignment_score: float = 50.0


@dataclass(frozen=True)
class CombinationRule:
    """Pairwise overlay for the generic goal-combination engine."""

    goal_a: GoalId
    goal_b: GoalId
    compatibility: CompatibilityLevel
    target_resolution: dict[str, str] = field(default_factory=dict)
    priority_resolution: str = "max_of_shared"
    conflict_severity: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class NutritionTargets:
    """Target outputs only — never treated as measured intake.

    Percent / gram / litre fields are TARGET ranges from configuration.
    Absolute ``protein_g`` / ``carbohydrate_g`` are weight-scaled TARGETS
    (g/kg × body weight) when weight is available — still not estimated intake.
    """

    protein_g_per_kg: TargetRange | None = None
    carbohydrate_g_per_kg: TargetRange | None = None
    fibre_priority: str | None = None
    hydration_priority: str | None = None
    energy_concept: str | None = None
    # Phase 11 — Healthy-band macro / fibre / water TARGETS
    carbohydrate_percent: TargetRange | None = None
    protein_percent: TargetRange | None = None
    fat_percent: TargetRange | None = None
    fibre_g: TargetRange | None = None
    water_l: TargetRange | None = None
    protein_g: TargetRange | None = None
    carbohydrate_g: TargetRange | None = None
    activity_band: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class IndicatorScore:
    """Scored behavioural proxy (0–100), or missing when not observable.

    ``score`` is None when required source fields are absent — not assumed poor
    behaviour. Priority/relevance are copied from config for later phases;
    they do not alter the raw behaviour score.
    """

    indicator_id: str
    score: float | None
    source_fields: tuple[str, ...]
    is_behavioural_proxy: bool = True
    general_quality_priority: PriorityLevel | None = None
    goal_relevance: dict[GoalId, PriorityLevel] = field(default_factory=dict)


@dataclass(frozen=True)
class GeneralQualityResult:
    """Goal-independent General Nutrition Quality (Phase 8).

    ``general_quality`` is None when no usable indicator evidence exists
    (insufficient data — not a fabricated poor score).
    """

    general_quality: float | None
    indicators_used: tuple[str, ...] = ()
    indicators_missing: tuple[str, ...] = ()
    total_weight: float = 0.0
    weights_used: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class GoalAlignmentResult:
    """Goal Alignment from behavioural scores × combined goal priorities (Phase 9).

    ``goal_alignment`` is None when there are zero goals (deferred to Phase 10
    renormalization) or when no usable indicator evidence exists.
    Does not measure target adherence or invent intake.
    """

    goal_alignment: float | None
    indicators_used: tuple[str, ...] = ()
    indicators_missing: tuple[str, ...] = ()
    total_weight: float = 0.0
    weights_used: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class FinalScoreResult:
    """Final nutrition behaviour score (Phase 10).

    ``final_score`` is None when neither General Quality nor Goal Alignment is
    usable (insufficient data — not a fabricated poor score).
    Does not apply risk bands, targets, or intake estimates.
    """

    final_score: float | None
    general_quality: float | None
    goal_alignment: float | None
    general_quality_weight_used: float = 0.0
    goal_alignment_weight_used: float = 0.0


@dataclass(frozen=True)
class NutritionResult:
    """Internal engine result before legacy output adaptation.

    ``nutrition_score`` polarity: higher = better behaviour quality.
    Does not include fabricated macro intake estimates.
    """

    general_quality: float
    goal_alignment: float | None
    nutrition_score: float
    risk_band: str
    goals: tuple[GoalId, ...]
    indicators: tuple[IndicatorScore, ...]
    targets: NutritionTargets
    general_quality_weight: float
    goal_alignment_weight: float


@dataclass(frozen=True)
class CombinedNutritionProfile:
    """Merged profile produced by the generic goal-combination engine.

    Targets stored here are configuration/target concepts only — never measured
    intake. Audit fields support debugging; they are not API outputs.
    """

    goals: tuple[GoalId, ...]
    compatibility: CompatibilityLevel | None
    priority_levels: dict[str, PriorityLevel]
    target_keys: tuple[str, ...]
    conflict_resolutions: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    # Phase 6 fields (defaults keep earlier constructions valid).
    merged_targets: NutritionTargets | None = None
    priority_resolution: str | None = None
    target_resolution_applied: dict[str, str] = field(default_factory=dict)
    conflict_severity: str | None = None
    food_quality_priorities: tuple[str, ...] = ()
    activity_dependencies: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ScaleValue:
    """Canonical scale answer (value + unit). Not an intake estimate."""

    value: float | int | None
    unit: str | None = None


@dataclass(frozen=True)
class NormalizedAnswers:
    """Canonical questionnaire representation after Input Normalization.

    Contains option codes / scale values only. Does not score behaviours,
    invent goals, or fabricate intake/target values.
    """

    health_priority_codes: tuple[str, ...]
    gender: str | None = None
    age: int | None = None
    height: ScaleValue | None = None
    weight: ScaleValue | None = None
    diet_preference: str | None = None
    food_groups: tuple[str, ...] | None = None
    healthy_breakfast_frequency: str | None = None
    fresh_fruit_frequency: str | None = None
    fresh_vegetable_frequency: str | None = None
    baked_goods_frequency: str | None = None
    dessert_frequency: str | None = None
    butter_dish_frequency: str | None = None
    red_meat_frequency: str | None = None
    red_meat_frequency_defaulted: bool = False
    extra_salt_frequency: str | None = None
    iodized_salt_status: str | None = None
    caffeine_frequency: str | None = None
    caffeine_type: tuple[str, ...] | None = None
    water_intake_frequency: str | None = None
    sickness_frequency: str | None = None
    exercise_frequency_week: str | None = None
    exercise_level: str | None = None
    physical_activity_frequency: str | None = None
    daily_active_duration: str | None = None
    sleeping_hours: str | None = None
    alcohol_frequency: str | None = None
    tobacco_frequency: str | None = None
    goal_preference: str | None = None
    weight_loss_goal: ScaleValue | None = None
    waist_circumference: ScaleValue | None = None
    waist_input_unit: str | None = None
    body_fat_percent: float | None = None


ConfidenceLevel = Literal["HIGH", "MEDIUM", "LOW", "INSUFFICIENT"]

CONFIDENCE_LEVELS: tuple[ConfidenceLevel, ...] = (
    "HIGH",
    "MEDIUM",
    "LOW",
    "INSUFFICIENT",
)


@dataclass(frozen=True)
class WaterEstimate:
    """Beverage-water range from questionnaire glasses. Not total body water."""

    low_l: float | None
    high_l: float | None
    confidence: ConfidenceLevel
    available: bool
    note: str = ""


@dataclass(frozen=True)
class FibreEstimate:
    """Bounded questionnaire fibre estimate. Not a precise gram measurement."""

    low_g: float | None
    high_g: float | None
    tier: str | None
    confidence: ConfidenceLevel
    available: bool
    note: str = ""


@dataclass(frozen=True)
class CarbohydratePattern:
    """Qualitative carbohydrate-quality pattern. Not % or grams."""

    pattern: str | None
    confidence: ConfidenceLevel
    available: bool
    note: str = ""


@dataclass(frozen=True)
class ProteinPattern:
    """Protein source-variety tier. Not protein grams or percentage."""

    adequacy_tier: str | None
    confidence: ConfidenceLevel
    available: bool
    note: str = ""


@dataclass(frozen=True)
class FatPattern:
    """Added/saturated-fat tendency. Not total fat grams or percentage."""

    tendency: str | None
    confidence: ConfidenceLevel
    available: bool
    note: str = ""


@dataclass(frozen=True)
class EstimatedMacroPercent:
    """Questionnaire-based estimated energy share. Not measured intake.

    ``central`` is internal only — user-facing output uses ``lower``–``upper``.
    """

    lower: int
    upper: int
    central: float
    confidence: ConfidenceLevel
    pattern: str | None = None


@dataclass(frozen=True)
class EstimatedNutritionIntake:
    """Phase 12 current-consumption estimate. Independent of Nutrition Score."""

    water: WaterEstimate
    fibre: FibreEstimate
    carbohydrate: CarbohydratePattern
    protein: ProteinPattern
    fat: FatPattern
    estimated_carbohydrate_percent: EstimatedMacroPercent | None = None
    estimated_protein_percent: EstimatedMacroPercent | None = None
    estimated_fat_percent: EstimatedMacroPercent | None = None


@dataclass(frozen=True)
class CurrentBodyMetrics:
    """Current body measurements. Calculated or from questionnaire, never fabricated."""

    bmr_kcal: float | None = None
    waist_cm: float | None = None
    body_fat_percent: float | None = None


@dataclass(frozen=True)
class IdealBodyMetrics:
    """Goal-aware ideal body metric target ranges from configuration."""

    ideal_bmr: TargetRange | None = None
    ideal_waist_cm: TargetRange | None = None
    waist_input_unit: str | None = None
    ideal_body_fat_percent: TargetRange | None = None


@dataclass(frozen=True)
class NutritionUserResult:
    """Phase 13 user-facing composition of score + current + ideal.

    ``nutrition_score`` is the whole-number display value.
    ``nutrition_score_raw`` is the unchanged internal float.
    Does not expose General Quality / Goal Alignment.
    """

    nutrition_score: int | None
    nutrition_score_raw: float | None
    current_nutrition: EstimatedNutritionIntake
    goal_based_ideal: NutritionTargets | None
    goals: tuple[GoalId, ...]
    risk_band: str | None = None
    current_body_metrics: CurrentBodyMetrics | None = None
    ideal_body_metrics: IdealBodyMetrics | None = None
    disclaimer: str = (
        "A questionnaire-based estimate of your dietary pattern — not a measurement. "
        "Estimated from the dietary patterns you reported, not from measured food "
        "amounts. Your actual intake may differ."
    )
