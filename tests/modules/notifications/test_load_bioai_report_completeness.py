"""Unit tests for BioAI load report completeness helpers."""

from modules.bioai_report.pdf_registration import is_metsights_hosted_report_url
from modules.notifications.load_bioai_reports import (
    _bioai_report_data_complete,
    _has_usable_report_url,
    _has_usable_reports,
    _report_data_complete,
    _report_url_for_bio_ai_registration,
)


def test_has_usable_reports():
    assert not _has_usable_reports(None)
    assert not _has_usable_reports({})
    assert not _has_usable_reports("   ")
    assert _has_usable_reports({"record_id": "x"})
    assert _has_usable_reports('{"record_id": "x"}')


def test_has_usable_report_url():
    assert not _has_usable_report_url(None)
    assert not _has_usable_report_url("")
    assert _has_usable_report_url("https://bio-ai-reports.example/r/slug")


def test_report_data_complete():
    assert not _report_data_complete(None, "https://example.com/r/x")
    assert not _report_data_complete({"a": 1}, None)
    assert _report_data_complete({"a": 1}, "https://example.com/r/x")


def test_metsights_hosted_report_url():
    assert is_metsights_hosted_report_url(
        "https://storages.metsights.com/reports/ABC_User_MHR.pdf"
    )
    assert not is_metsights_hosted_report_url(
        "https://bio-ai-reports.supershyft.com/r/my-slug"
    )


def test_bioai_complete_requires_non_metsights_pdf():
    reports = {"record_id": "ABC"}
    metsights_pdf = "https://storages.metsights.com/reports/ABC_User_MHR.pdf"
    bio_slug = "https://bio-ai-reports.supershyft.com/r/slug"

    assert _report_data_complete(reports, metsights_pdf)
    assert not _bioai_report_data_complete(reports, metsights_pdf)
    assert _bioai_report_data_complete(reports, bio_slug)
    assert _report_url_for_bio_ai_registration(metsights_pdf) is None
    assert _report_url_for_bio_ai_registration(bio_slug) == bio_slug
