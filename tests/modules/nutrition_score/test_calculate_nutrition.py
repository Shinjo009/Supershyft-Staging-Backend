"""Smoke tests for the in-process nutrition score engine."""

from __future__ import annotations

import json
from pathlib import Path

from modules.nutrition_score import calculate_nutrition

_SAMPLE_PAYLOAD_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "nutrition_sample_payload.json"


def test_calculate_nutrition_returns_health_span_contract():
    payload = json.loads(_SAMPLE_PAYLOAD_PATH.read_text(encoding="utf-8"))
    result = calculate_nutrition(payload)

    assert isinstance(result, dict)
    assert result["nutrition_score"] == 95
    assert result["risk_band"] == "Healthy"
    assert set(result.keys()) >= {
        "nutrition_score",
        "risk_band",
        "carbs",
        "fats",
        "protein",
        "fibre",
        "water",
        "ideal_bmr",
        "ideal_waist",
        "ideal_body_fat",
        "disclaimer",
        "goals",
    }
    assert result["carbs"]["status"] in {"within_ideal", "above_ideal", "below_ideal", None}


def test_calculate_nutrition_rejects_non_object_payload():
    try:
        calculate_nutrition(["not", "an", "object"])  # type: ignore[arg-type]
    except TypeError as exc:
        assert "JSON object" in str(exc)
    else:
        raise AssertionError("expected TypeError for non-object payload")
