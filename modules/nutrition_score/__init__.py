"""Nutrition Intelligence Engine — in-process scoring for Health Span and camp reports."""

from modules.nutrition_score.nutrition_engine import calculate_nutrition

NUTRITION_INTERNAL_ENDPOINT = "internal://nutrition_score/calculate"

__all__ = ["calculate_nutrition", "NUTRITION_INTERNAL_ENDPOINT"]
