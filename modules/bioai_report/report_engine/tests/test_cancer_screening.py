"""Cancer screening JSON: gender order, source fidelity, and report compatibility."""

from __future__ import annotations

import json

from modules.bioai_report.report_engine.builders.report_builder import build_bioreport
from modules.bioai_report.report_engine.knowledge_base.loader import KnowledgeBaseStore

MALE = (
    "pancreatic_cancer",
    "colorectal_cancer",
    "liver_cancer",
    "prostate_cancer",
)
FEMALE = (
    "pancreatic_cancer",
    "colorectal_cancer",
    "liver_cancer",
    "breast_cancer",
    "ovarian_cancer",
)


def _disease(code: str, name: str, score: int, status: str = "Increased") -> dict:
    return {
        "code": code,
        "name": name,
        "risk_status": status,
        "risk_score_scaled": score,
    }


def _assessment(*, gender: str | None, diseases: list[dict], markers: list[dict] | None = None) -> dict:
    body: dict = {
        "record_id": "fixture-cancer",
        "age": 50,
        "gender": gender,
        "metabolic_score": 70,
        "diseases": diseases,
    }
    if markers is not None:
        body["biomarkers"] = markers
    return {"data": body}


def _report(**kwargs):
    return build_bioreport(_assessment(**kwargs), record_id="fixture-cancer")


def test_knowledge_base_lengths():
    store = KnowledgeBaseStore()
    for code in (
        "pancreatic_cancer",
        "colorectal_cancer",
        "liver_cancer",
        "prostate_cancer",
        "breast_cancer",
        "ovarian_cancer",
    ):
        item = store.get_cancer(code)
        assert item.definition.content.strip()
        assert len(item.actionable_insights.items) == 3
        assert len(item.influencing_factors.items) == 3
        assert all(text.strip() for text in item.actionable_insights.items)
        assert all(text.strip() for text in item.influencing_factors.items)


def test_male_predicted_risk_order():
    report = _report(
        gender="male",
        diseases=[
            _disease("prostate_cancer", "Prostrate Cancer", 80, "Very High"),
            _disease("liver_cancer", "Liver Cancer", 10, "Healthy"),
            _disease("colorectal_cancer", "Colorectal Cancer", 40, "Increased"),
            _disease("pancreatic_cancer", "Pancreatic Cancer", 20, "Healthy"),
            _disease("breast_cancer", "Breast Cancer", 55, "High"),
        ],
    )
    codes = [item.cancer_code for item in report.individual_cancer_information]
    assert codes == list(MALE) + ["breast_cancer"]
    assert [card.cancer_code for card in report.detailed_cancer_screening.cancer_results] == codes
    prostate = report.detailed_cancer_screening.cancer_results[3]
    assert prostate.result_type == "predicted_risk"
    assert prostate.predicted_risk == 80
    assert prostate.display_status == "critical"
    assert prostate.marker_name is None
    assert report.detailed_cancer_screening.snapshot.total_markers == 0
    assert report.detailed_cancer_screening.gender_filter_note is None
    assert "diagnosis" in report.detailed_cancer_screening.key_insights.content.lower()


def test_female_five_categories_and_skips_prostate_when_absent():
    report = _report(
        gender="female",
        diseases=[
            _disease(code, code.replace("_", " "), 30)
            for code in FEMALE
        ],
    )
    codes = [item.cancer_code for item in report.individual_cancer_information]
    assert codes == list(FEMALE)
    for item in report.individual_cancer_information:
        assert len(item.actionable_insights.items) == 3
        assert len(item.influencing_factors.items) == 3


def test_partial_results_only():
    report = _report(
        gender="female",
        diseases=[_disease("breast_cancer", "Breast Cancer", 15, "Healthy")],
    )
    assert [item.cancer_code for item in report.individual_cancer_information] == ["breast_cancer"]


def test_missing_gender_keeps_matched_results_and_notes_filter():
    report = _report(
        gender=None,
        diseases=[
            _disease("prostate_cancer", "Prostate Cancer", 30),
            _disease("breast_cancer", "Breast Cancer", 30),
        ],
    )
    assert [item.cancer_code for item in report.individual_cancer_information] == [
        "prostate_cancer",
        "breast_cancer",
    ]
    note = report.detailed_cancer_screening.gender_filter_note or ""
    assert "could not be completed" in note


def test_elevated_and_normal_markers_are_not_called_critical():
    report = _report(
        gender="male",
        diseases=[_disease("prostate_cancer", "Prostate Cancer", 70, "High")],
        markers=[
            {
                "name": "PSA",
                "value": 12,
                "unit": "ng/mL",
                "reference_range": "0-4",
                "status": "High",
            },
            {
                "name": "AFP",
                "value": 3,
                "unit": "ng/mL",
                "reference_range": "0-10",
            },
        ],
    )
    cards = {card.cancer_code: card for card in report.detailed_cancer_screening.cancer_results}
    assert cards["prostate_cancer"].result_type == "biomarker"
    assert cards["prostate_cancer"].value == 12
    assert cards["prostate_cancer"].range_flag == "out_of_range"
    assert cards["prostate_cancer"].display_status == "unknown"
    assert cards["prostate_cancer"].predicted_risk == 70
    assert cards["liver_cancer"].range_flag == "in_range"
    assert cards["liver_cancer"].display_status == "optimal"
    snapshot = report.detailed_cancer_screening.snapshot
    assert snapshot.total_markers == 2
    assert snapshot.markers_out_of_range == 1
    assert snapshot.markers_in_range == 1
    assert snapshot.highlighted_markers[0].marker_name == "PSA"


def test_missing_reference_range_is_unknown():
    report = _report(
        gender="female",
        diseases=[],
        markers=[{"name": "CA 15-3", "value": 21, "unit": "U/mL"}],
    )
    card = report.detailed_cancer_screening.cancer_results[0]
    assert card.cancer_code == "breast_cancer"
    assert card.range_flag == "unknown"
    assert card.display_status == "unknown"
    assert card.reference_range is None
    assert report.detailed_cancer_screening.snapshot.markers_unknown == 1


def test_duplicate_alias_collapses_to_one_card():
    report = _report(
        gender="male",
        diseases=[
            _disease("prostate_cancer", "Prostate Cancer", 22, "Healthy"),
            _disease("prostrate", "Prostrate", 90, "Very High"),
        ],
    )
    prostate = [
        card
        for card in report.detailed_cancer_screening.cancer_results
        if card.cancer_code == "prostate_cancer"
    ]
    assert len(prostate) == 1
    assert prostate[0].predicted_risk == 22


def test_existing_disease_sections_and_json_order_stay_compatible():
    raw = {
        "data": {
            "record_id": "fixture-cancer",
            "gender": "male",
            "age": 40,
            "metabolic_score": 60,
            "diseases": [
                _disease("diabetes", "Type 2 diabetes", 30, "Increased"),
                _disease("obesity", "Obesity", 10, "Healthy"),
            ],
        }
    }
    report = build_bioreport(raw, record_id="fixture-cancer")
    payload = report.to_dict()
    keys = list(payload)
    assert keys.index("individual_cancer_information") < keys.index("detailed_cancer_screening")
    assert "disease_sections" in payload
    json.dumps(payload)
    assert payload["individual_cancer_information"] == []
    assert payload["detailed_cancer_screening"]["cancer_results"] == []
    assert payload["detailed_cancer_screening"]["snapshot"]["total_markers"] == 0
