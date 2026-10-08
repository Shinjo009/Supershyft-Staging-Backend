"""Unit tests for BioAI load report completeness helpers."""

from modules.notifications.load_bioai_reports import (
    _has_usable_report_url,
    _has_usable_reports,
    _report_data_complete,
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
