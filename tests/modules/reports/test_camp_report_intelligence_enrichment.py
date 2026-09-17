"""Tests for camp-report intelligence enrichment assembly."""

from __future__ import annotations

import copy

from modules.reports.camp_report_intelligence import (
    INTELLIGENCE_CAMP_SECTIONS,
    LEADERSHIP_TAKEAWAYS_SECTION,
    enrich_camp_report_with_intelligence,
    generate_report_insights,
)


def _gender_distribution(*, elevated_key: str = "rarely_or_never") -> dict:
    return {
        "male": {
            "group": ["less_than_30mins", "30_60_mins", "more_than_60_mins", elevated_key],
            "percent": [20.0, 30.0, 10.0, 40.0],
            "count": [10, 15, 5, 20],
        },
        "female": {
            "group": ["less_than_30mins", "30_60_mins", "more_than_60_mins", elevated_key],
            "percent": [25.0, 35.0, 15.0, 25.0],
            "count": [12, 18, 8, 12],
        },
    }


def _sleep_distribution() -> dict:
    return {
        "male": {
            "group": ["less_than_5hrs", "between_5_7_hrs", "between_7_9_hrs", "more_than_9hrs"],
            "percent": [15.0, 40.0, 35.0, 10.0],
            "count": [8, 20, 17, 5],
        },
        "female": {
            "group": ["less_than_5hrs", "between_5_7_hrs", "between_7_9_hrs", "more_than_9hrs"],
            "percent": [10.0, 45.0, 40.0, 5.0],
            "count": [5, 22, 20, 3],
        },
    }


def _disease_item(code: str) -> dict:
    groups = ["healthy", "increased", "high", "very_high"]
    return {
        "code": code,
        "male": {
            "group": groups,
            "percent": [40.0, 20.0, 25.0, 15.0],
            "count": [20, 10, 12, 8],
            "elevated_percent": 40.0,
        },
        "female": {
            "group": groups,
            "percent": [50.0, 20.0, 20.0, 10.0],
            "count": [25, 10, 10, 5],
            "elevated_percent": 30.0,
        },
    }


def sample_camp_report() -> dict:
    """Minimal camp report covering mapped + unmapped sections."""
    return {
        "meta": {"summary_available": True, "refreshed_at": "2026-08-10T00:00:00Z"},
        "kpis": {
            "data": {"male_enrolled": 50, "female_enrolled": 50, "total_enrolled": 100},
            "name": "KPIs",
            "description": "kpi-desc",
        },
        "participation_by_age": {
            "data": {
                "age_group": ["18–25", "26–35", "36–45"],
                "enrolled": [20, 40, 40],
                "percent": [20.0, 40.0, 40.0],
            },
            "name": "Participation by Age",
            "description": "participation-desc",
        },
        "overall_risk_score": {
            "data": {
                "group": ["optimal", "low_risk", "increased_risk", "high_risk"],
                "percent": [20.0, 30.0, 35.0, 15.0],
                "count": [20, 30, 35, 15],
            },
            "name": "Overall Risk Score",
            "description": None,
        },
        "distribution_by_physical_activity_frequency": {
            "data": _gender_distribution(),
            "name": "Physical Activity",
            "description": "pa-desc",
        },
        "distribution_by_sleeping_hours": {
            "data": _sleep_distribution(),
            "name": "Sleep",
            "description": "sleep-desc",
        },
        "distribution_by_oxidative_stress": {
            "data": {
                "group": ["low", "moderate", "high", "very_high"],
                "percent": [25.0, 35.0, 30.0, 10.0],
                "total_employees": 100,
            },
            "name": "Oxidative Stress",
            "description": None,
        },
        "distribution_by_gender_by_metabolic_syndrome": {
            "data": {
                "diseases": [
                    _disease_item("metabolic_syndrome"),
                    _disease_item("diabetes"),
                ]
            },
            "name": "Metabolic Syndrome",
            "description": "metabolic-desc",
        },
        "positive_wins": {
            "data": {
                "low_risk": [
                    {"code": "hypertension", "name": "Hypertension", "risk_status": "low"}
                ],
                "healthy_habits": [{"habit_label": "Regular exercise"}],
                "healthy_profiles": ["Balanced lifestyle"],
            },
            "name": "Positive Wins",
            "description": "wins-desc",
        },
        "blood_and_lab_intelligence": {
            "data": {"lipid_profile": {"ldl": {"in_range_percent": 70}}},
            "name": "Blood & Lab",
            "description": "blood-desc",
        },
        "company_average_scores": {
            "data": {
                "nutrition": {"score": 62},
                "fitness": {"score": 55},
                "lifestyle": {"score": 58},
            },
            "name": "Company Average Scores",
            "description": None,
        },
        "ranking": {
            "data": {"departments": []},
            "name": "Ranking",
            "description": "ranking-desc",
        },
    }


def test_enrich_preserves_top_level_keys_and_section_fields():
    original = sample_camp_report()
    snapshot = copy.deepcopy(original)

    enriched = enrich_camp_report_with_intelligence(original)

    extra = [key for key in enriched if key not in snapshot]
    assert extra == [LEADERSHIP_TAKEAWAYS_SECTION]
    assert list(snapshot.keys()) == [k for k in enriched.keys() if k != LEADERSHIP_TAKEAWAYS_SECTION]

    for key, section in snapshot.items():
        if key == "meta":
            assert enriched[key] == section
            continue
        assert enriched[key]["data"] == section["data"]
        assert enriched[key]["name"] == section["name"]
        assert enriched[key]["description"] == section["description"]

    # Input must not be mutated.
    assert original == snapshot
    assert "intelligence" not in original["overall_risk_score"]


def test_enrich_attaches_intelligence_to_mapped_sections_only():
    enriched = enrich_camp_report_with_intelligence(sample_camp_report())

    for section_key in INTELLIGENCE_CAMP_SECTIONS:
        assert "intelligence" in enriched[section_key], section_key

    for section_key in (
        "kpis",
        "blood_and_lab_intelligence",
        "company_average_scores",
        "ranking",
    ):
        assert enriched[section_key] == sample_camp_report()[section_key]
        assert "intelligence" not in enriched[section_key]

    assert "intelligence" not in enriched["meta"]


def test_enrich_does_not_include_profile_or_leadership_cards():
    enriched = enrich_camp_report_with_intelligence(sample_camp_report())

    assert "profile" not in enriched
    assert "leadership_cards" not in enriched
    assert "concerns" not in enriched
    assert "positives" not in enriched
    assert LEADERSHIP_TAKEAWAYS_SECTION in enriched

    raw = generate_report_insights(sample_camp_report())
    assert "profile" in raw
    assert "leadership_cards" in raw


def test_enrich_metabolic_and_positives_structure():
    enriched = enrich_camp_report_with_intelligence(sample_camp_report())

    metabolic = enriched["distribution_by_gender_by_metabolic_syndrome"]["intelligence"]
    assert isinstance(metabolic, dict)
    assert "disease_risks" in metabolic
    assert "disease_deep_dive" in metabolic
    assert isinstance(metabolic["disease_deep_dive"], dict)

    positives = enriched["positive_wins"]["intelligence"]
    assert set(positives) == {"low_risk_diseases", "healthy_habits", "healthy_blood_profiles"}
    assert positives["low_risk_diseases"]["tone"] == "positive"
    assert "Hypertension" in positives["low_risk_diseases"]["statement"]
    assert "Regular exercise" in positives["healthy_habits"]["statement"]
    assert "Balanced lifestyle" in positives["healthy_blood_profiles"]["statement"]


def test_positive_wins_keeps_all_three_frontend_buckets():
    report = sample_camp_report()
    report["positive_wins"]["data"] = {
        "low_risk": [{"code": "thyroid_health", "name": "Thyroid Health"}],
        "healthy_habits": [],
        "healthy_profiles": [],
    }
    enriched = enrich_camp_report_with_intelligence(report)
    positives = enriched["positive_wins"]["intelligence"]
    assert set(positives) == {"low_risk_diseases", "healthy_habits", "healthy_blood_profiles"}
    assert "Thyroid Health" in positives["low_risk_diseases"]["statement"]
    assert positives["healthy_habits"]["statement"]
    assert positives["healthy_blood_profiles"]["statement"]


def test_enrich_lifestyle_sections_have_gender_views():
    enriched = enrich_camp_report_with_intelligence(sample_camp_report())

    for section_key in (
        "distribution_by_physical_activity_frequency",
        "distribution_by_sleeping_hours",
    ):
        intel = enriched[section_key]["intelligence"]
        assert set(intel.keys()) >= {"both", "male", "female"}
        assert intel["male"]["statement"] != intel["female"]["statement"]


_FORBIDDEN_PUBLIC_INTEL_KEYS = frozenset(
    {
        "structured",
        "severity_band",
        "confidence",
        "effect_ids",
        "lever_ids",
        "related_metrics",
        "notes",
        "section_id",
        "mode",
        "text",
    }
)


def _walk_intelligence(node: object):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_intelligence(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_intelligence(item)


def test_enrich_public_intelligence_is_frontend_contract_only():
    original = sample_camp_report()
    raw = generate_report_insights(original)
    overall_raw = (raw.get("concerns") or {}).get("overall_risk") or {}
    assert "structured" in overall_raw
    assert "confidence" in overall_raw

    enriched = enrich_camp_report_with_intelligence(original)
    overall = enriched["overall_risk_score"]["intelligence"]
    assert set(overall.keys()) == {"tone", "statement"}
    assert overall["tone"]
    assert overall["statement"]

    structured = (overall_raw.get("structured") or {})
    assert structured.get("observation")
    assert structured.get("observation") in overall["statement"]
    assert overall["tone"] == overall_raw.get("tone") or structured.get("tone")

    for section_key in INTELLIGENCE_CAMP_SECTIONS:
        for node in _walk_intelligence(enriched[section_key]["intelligence"]):
            leaked = _FORBIDDEN_PUBLIC_INTEL_KEYS.intersection(node)
            assert not leaked, f"{section_key} leaked {sorted(leaked)} in {list(node)}"


def test_enrich_skips_missing_sections_without_creating_them():
    report = {
        "meta": {},
        "overall_risk_score": {
            "data": {
                "group": ["optimal", "low_risk", "increased_risk", "high_risk"],
                "percent": [40.0, 30.0, 20.0, 10.0],
                "count": [40, 30, 20, 10],
            },
            "name": "Overall Risk Score",
            "description": None,
        },
        "kpis": {
            "data": {"male_enrolled": 10, "female_enrolled": 10},
            "name": "KPIs",
            "description": None,
        },
    }
    enriched = enrich_camp_report_with_intelligence(report)

    assert set(enriched.keys()) == set(report.keys()) | {LEADERSHIP_TAKEAWAYS_SECTION}
    assert "intelligence" in enriched["overall_risk_score"]
    assert "intelligence" not in enriched["kpis"]
    assert "participation_by_age" not in enriched
    assert "positive_wins" not in enriched
    takeaways = enriched[LEADERSHIP_TAKEAWAYS_SECTION]
    intel = takeaways["intelligence"]
    assert isinstance(intel, dict)
    assert "workforce_health" in intel
    assert set(intel["workforce_health"].keys()) == {"tone", "statement"}
    assert intel["workforce_health"]["statement"]
    assert intel["workforce_health"]["tone"] in {"positive", "concern"}
    assert "strategic_next_step" in intel
    assert intel["strategic_next_step"]["statement"]


def test_enrich_empty_report_does_not_fabricate_leadership_or_wins():
    enriched = enrich_camp_report_with_intelligence({"meta": {}})
    assert enriched[LEADERSHIP_TAKEAWAYS_SECTION]["intelligence"] == {}
    assert "positive_wins" not in enriched


def test_leadership_takeaways_match_raw_leadership_cards():
    original = sample_camp_report()
    raw = generate_report_insights(original)
    enriched = enrich_camp_report_with_intelligence(original)
    intel = enriched[LEADERSHIP_TAKEAWAYS_SECTION]["intelligence"]
    raw_cards = raw["leadership_cards"]
    assert len(intel) == len(raw_cards) == 4
    for internal in raw_cards:
        key = str(internal["id"]).replace("-", "_")
        public = intel[key]
        structured = internal.get("structured") or {}
        assert set(public.keys()) == {"tone", "statement"}
        assert public["tone"] == structured.get("tone")
        assert structured.get("observation") in public["statement"]
        assert "confidence" not in public
        assert "structured" not in public


def test_leadership_takeaways_do_not_repeat_sentences():
    enriched = enrich_camp_report_with_intelligence(sample_camp_report())
    intel = enriched[LEADERSHIP_TAKEAWAYS_SECTION]["intelligence"]
    sentences: list[str] = []
    for block in intel.values():
        for part in (block["statement"] or "").split(". "):
            key = part.strip().rstrip(".").lower()
            if key:
                sentences.append(key)
    assert len(sentences) == len(set(sentences))
    blob = " ".join(sentences)
    assert "early, coordinated preventive action" not in blob


def _statement_sentences(intel: dict) -> list[str]:
    sentences: list[str] = []
    for block in intel.values():
        if not isinstance(block, dict):
            continue
        statement = block.get("statement")
        if not isinstance(statement, str):
            continue
        for part in statement.split(". "):
            key = part.strip().rstrip(".").lower()
            if key:
                sentences.append(key)
    return sentences


def test_lifestyle_gender_views_do_not_repeat_sentences():
    enriched = enrich_camp_report_with_intelligence(sample_camp_report())
    for section_key in (
        "distribution_by_sleeping_hours",
        "distribution_by_physical_activity_frequency",
    ):
        sentences = _statement_sentences(enriched[section_key]["intelligence"])
        assert sentences
        assert len(sentences) == len(set(sentences)), section_key
