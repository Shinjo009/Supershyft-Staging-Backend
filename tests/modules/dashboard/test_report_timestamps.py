"""Unit tests for report / consultation timestamp stamp helpers."""

from __future__ import annotations

from types import SimpleNamespace

from modules.reports.report_timestamps import (
    mark_consultation_done,
    set_bioai_report_url,
    set_diagnostic_report_url,
)


def test_set_diagnostic_report_url_stamps_on_first_set():
    row = SimpleNamespace(diagnostic_report_url=None, report_received_at=None)
    set_diagnostic_report_url(row, "https://example.com/a.pdf")
    assert row.diagnostic_report_url == "https://example.com/a.pdf"
    assert row.report_received_at is not None
    stamped = row.report_received_at
    set_diagnostic_report_url(row, "https://example.com/a.pdf")
    assert row.report_received_at == stamped


def test_set_diagnostic_report_url_clears_stamp():
    row = SimpleNamespace(diagnostic_report_url="https://example.com/a.pdf", report_received_at="keep")
    set_diagnostic_report_url(row, None)
    assert row.diagnostic_report_url is None
    assert row.report_received_at is None


def test_set_bioai_report_url_stamps():
    row = SimpleNamespace(report_url=None, report_received_at=None)
    set_bioai_report_url(row, "https://bio.example/r/1")
    assert row.report_url == "https://bio.example/r/1"
    assert row.report_received_at is not None


def test_mark_consultation_done_stamps_once():
    booking = SimpleNamespace(done=False, consultation_done_at=None)
    mark_consultation_done(booking)
    assert booking.done is True
    assert booking.consultation_done_at is not None
    first = booking.consultation_done_at
    mark_consultation_done(booking)
    assert booking.consultation_done_at == first
