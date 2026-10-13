"""Canonical IHR subquery must not reference blood columns moved off IHR in 0145."""

from __future__ import annotations

from modules.reports.models import IndividualHealthReport
from modules.reports.repository import ReportsRepository


def test_ihr_model_has_no_blood_columns():
    assert not hasattr(IndividualHealthReport, "blood_parameters")
    assert not hasattr(IndividualHealthReport, "blood_report_raw")
    assert not hasattr(IndividualHealthReport, "diagnostic_report_url")


def test_canonical_ihr_subquery_compiles_without_blood_columns():
    compiled = str(
        ReportsRepository.canonical_individual_health_report_subquery().compile(
            compile_kwargs={"literal_binds": True}
        )
    ).lower()
    assert "blood_parameters" not in compiled
    assert "blood_report_raw" not in compiled
    assert "diagnostic_report_url" not in compiled
    assert "report_url" in compiled
    assert "reports" in compiled
