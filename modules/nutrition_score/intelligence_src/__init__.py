"""Nutrition Intelligence Engine.

Pure Python core with a thin ReportsService/Health Span adapter in ``engine.py``.
"""

from __future__ import annotations

from modules.nutrition_score.intelligence_src.behaviour import evaluate_behaviour_indicators
from modules.nutrition_score.intelligence_src.body_metrics import (
    resolve_ideal_bmr,
    resolve_ideal_body_metrics,
)
from modules.nutrition_score.intelligence_src.config_loader import (
    BodyMetricTargetConfig,
    NutritionEngineConfig,
    default_config_dir,
    load_nutrition_engine_config,
)
from modules.nutrition_score.intelligence_src.engine import (
    calculate_nutrition_intelligence,
    run_nutrition_intelligence_from_lookup,
    serialize_health_span_nutrition,
)
from modules.nutrition_score.intelligence_src.goals import (
    combine_goal_profiles,
    load_goal_profiles,
    resolve_goal_codes,
    resolve_goals,
)
from modules.nutrition_score.intelligence_src.models import (
    CarbohydratePattern,
    CombinationRule,
    CombinedNutritionProfile,
    CurrentBodyMetrics,
    ConfidenceLevel,
    EstimatedMacroPercent,
    EstimatedNutritionIntake,
    FatPattern,
    FibreEstimate,
    FinalScoreResult,
    GeneralQualityResult,
    GoalAlignmentResult,
    GoalId,
    GoalProfile,
    IdealBodyMetrics,
    IndicatorDefinition,
    IndicatorScore,
    NormalizedAnswers,
    NutritionResult,
    NutritionTargets,
    NutritionUserResult,
    PriorityLevel,
    ProteinPattern,
    ScaleValue,
    ScoreBand,
    ScoringConfig,
    TargetRange,
    WaterEstimate,
)
from modules.nutrition_score.intelligence_src.nutrition import estimate_current_nutrition
from modules.nutrition_score.intelligence_src.questionnaire import normalize_questionnaire_lookup
from modules.nutrition_score.intelligence_src.result import compose_user_result, format_user_result
from modules.nutrition_score.intelligence_src.scoring import (
    calculate_final_score,
    calculate_general_quality,
    calculate_goal_alignment,
    display_nutrition_score,
    resolve_risk_band,
)
from modules.nutrition_score.intelligence_src.targets import (
    derive_activity_band,
    generate_nutrition_targets,
)

__all__ = [
    "CarbohydratePattern",
    "BodyMetricTargetConfig",
    "CombinationRule",
    "CombinedNutritionProfile",
    "CurrentBodyMetrics",
    "ConfidenceLevel",
    "EstimatedMacroPercent",
    "EstimatedNutritionIntake",
    "FatPattern",
    "FibreEstimate",
    "FinalScoreResult",
    "GeneralQualityResult",
    "GoalAlignmentResult",
    "GoalId",
    "GoalProfile",
    "IdealBodyMetrics",
    "IndicatorDefinition",
    "IndicatorScore",
    "NormalizedAnswers",
    "NutritionEngineConfig",
    "NutritionResult",
    "NutritionTargets",
    "NutritionUserResult",
    "PriorityLevel",
    "ProteinPattern",
    "ScaleValue",
    "ScoreBand",
    "ScoringConfig",
    "TargetRange",
    "WaterEstimate",
    "calculate_final_score",
    "calculate_general_quality",
    "calculate_goal_alignment",
    "calculate_nutrition_intelligence",
    "combine_goal_profiles",
    "compose_user_result",
    "default_config_dir",
    "derive_activity_band",
    "display_nutrition_score",
    "estimate_current_nutrition",
    "evaluate_behaviour_indicators",
    "format_user_result",
    "generate_nutrition_targets",
    "load_goal_profiles",
    "load_nutrition_engine_config",
    "normalize_questionnaire_lookup",
    "resolve_goal_codes",
    "resolve_goals",
    "resolve_ideal_bmr",
    "resolve_ideal_body_metrics",
    "resolve_risk_band",
    "run_nutrition_intelligence_from_lookup",
    "serialize_health_span_nutrition",
]
