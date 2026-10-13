"""End-to-end cancer screening through the production BioReport assembly path.

Uses stored assessment fixtures, then the same ``generate_from_assessment``
method the API uses after the report JSON is loaded.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from modules.bioai_report.report_engine.knowledge_base.loader import KnowledgeBaseStore
from modules.bioai_report.report_engine.services.report_service import BioReportService

FIXTURES = Path(__file__).resolve().parents[2] / "test_engine"
MALE_ORDER = (
    "pancreatic_cancer",
    "colorectal_cancer",
    "liver_cancer",
    "prostate_cancer",
)
FEMALE_ORDER = (
    "pancreatic_cancer",
    "colorectal_cancer",
    "liver_cancer",
    "breast_cancer",
    "ovarian_cancer",
)


def _service() -> BioReportService:
    return BioReportService(
        assessment_service=None,  # type: ignore[arg-type]
        patient_service=None,
        kb_store=KnowledgeBaseStore(),
    )


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _disease(code: str, name: str, score: int, status: str) -> dict:
    return {
        "code": code,
        "name": name,
        "risk_status": status,
        "risk_score_scaled": score,
        "lifestyle_contribution": None,
        "disease_percentile": 40,
        "healthy_percentile": 70,
    }


def _with_cancer(fixture_name: str, *, gender: str, diseases: list[dict], markers: list[dict]) -> dict:
    raw = copy.deepcopy(_load(fixture_name))
    body = raw["data"]
    body["gender"] = gender
    body["sex"] = gender
    body["diseases"] = list(body["diseases"]) + diseases
    body["biomarkers"] = markers
    return body


def test_real_fixtures_keep_disease_sections_and_empty_cancer_blocks():
    service = _service()
    for name in ("VivekShah.json", "Harshili.json", "report_user1.json"):
        body = _load(name)["data"]
        report = service.generate_from_assessment(body, record_id=str(body["record"]))
        payload = json.loads(json.dumps(report.to_dict()))
        keys = list(payload)
        assert keys.index("individual_cancer_information") < keys.index("detailed_cancer_screening")
        assert payload["report_metadata"]["disease_count"] == len(payload["disease_sections"])
        assert payload["report_metadata"]["disease_count"] > 0
        assert payload["individual_cancer_information"] == []
        screening = payload["detailed_cancer_screening"]
        assert screening["cancer_results"] == []
        assert screening["snapshot"]["total_markers"] == 0
        assert screening["introduction"]["heading"] == "What is cancer?"


def test_male_fixture_e2e_matches_knowledge_base_and_marker_math():
    service = _service()
    body = _with_cancer(
        "VivekShah.json",
        gender="male",
        diseases=[
            _disease("pancreatic_cancer", "Pancreatic Cancer", 18, "Healthy"),
            _disease("colorectal_cancer", "Colorectal Cancer", 42, "Increased"),
            _disease("liver_cancer", "Liver Cancer", 12, "Healthy"),
            _disease("prostrate", "Prostrate Cancer", 61, "High"),
            _disease("prostate_cancer", "Prostate Cancer", 90, "Very High"),
        ],
        markers=[
            {"name": "PSA", "value": 2.1, "unit": "ng/mL", "reference_range": "0-4"},
            {"name": "AFP", "value": 14, "unit": "ng/mL", "reference_range": "0-10"},
        ],
    )
    report = service.generate_from_assessment(body, record_id=str(body["record"]))
    payload = report.to_dict()
    pages = payload["individual_cancer_information"]
    screening = payload["detailed_cancer_screening"]
    assert [page["cancer_code"] for page in pages] == list(MALE_ORDER)
    assert [card["cancer_code"] for card in screening["cancer_results"]] == list(MALE_ORDER)
    store = KnowledgeBaseStore()
    for page in pages:
        education = store.get_cancer(page["cancer_code"])
        assert page["definition"]["content"] == education.definition.content
        assert page["actionable_insights"]["items"] == education.actionable_insights.items
        assert page["influencing_factors"]["items"] == education.influencing_factors.items
        assert len(page["actionable_insights"]["items"]) == 3
        assert len(page["influencing_factors"]["items"]) == 3
    cards = {card["cancer_code"]: card for card in screening["cancer_results"]}
    assert cards["prostate_cancer"]["predicted_risk"] == 61
    assert cards["prostate_cancer"]["marker_name"] == "PSA"
    assert cards["prostate_cancer"]["value"] == 2.1
    assert cards["prostate_cancer"]["range_flag"] == "in_range"
    assert cards["liver_cancer"]["value"] == 14
    assert cards["liver_cancer"]["range_flag"] == "out_of_range"
    assert cards["liver_cancer"]["display_status"] == "unknown"
    snapshot = screening["snapshot"]
    assert snapshot["total_markers"] == 2
    assert snapshot["markers_in_range"] == 1
    assert snapshot["markers_out_of_range"] == 1
    assert snapshot["highlighted_markers"][0]["marker_name"] == "AFP"
    assert "does not diagnose cancer" in screening["key_insights"]["content"]
    assert any(section["disease_id"] == "type2_diabetes" for section in payload["disease_sections"])
    json.dumps(payload)


def test_female_fixture_e2e_orders_five_cancers():
    body = _with_cancer(
        "Harshili.json",
        gender="female",
        diseases=[_disease(code, code, 25, "Healthy") for code in FEMALE_ORDER],
        markers=[{"name": "CA 15-3", "value": 40, "unit": "U/mL", "reference_range": "0-30"}],
    )
    payload = _service().generate_from_assessment(body, record_id=str(body["record"])).to_dict()
    assert [page["section_title"] for page in payload["individual_cancer_information"]] == [
        "Pancreatic Cancer Screening",
        "Colorectal Cancer Screening",
        "Liver Cancer Screening (AFP)",
        "Breast Cancer Screening (Female)",
        "Ovarian Cancer Screening (Female)",
    ]
    breast = payload["detailed_cancer_screening"]["cancer_results"][3]
    assert breast["cancer_code"] == "breast_cancer"
    assert breast["value"] == 40
    assert breast["result_type"] == "biomarker"
    assert payload["detailed_cancer_screening"]["snapshot"]["markers_out_of_range"] == 1
    assert any(section["disease_id"] == "pcos" for section in payload["disease_sections"])
