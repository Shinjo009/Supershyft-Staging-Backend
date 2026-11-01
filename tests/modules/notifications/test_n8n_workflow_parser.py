"""Tests for n8n workflow JSON parser."""

from __future__ import annotations

from pathlib import Path

from modules.notifications.n8n_workflow_parser import (
    body_parameter_count,
    parse_workflow_file,
    parse_workflows_dir,
)

WORKFLOWS = Path(__file__).resolve().parents[3] / "n8n" / "workflows"


def test_booking_confirmation_whatsapp_camp17_seven_params():
    parsed = parse_workflow_file(WORKFLOWS / "booking-confirmation-whatsapp.json")
    assert parsed is not None
    assert parsed.template_name == "camp17"
    count = body_parameter_count(parsed.template_variables)
    assert count >= 7
    assert count == 8


def test_whatapi_otp_template():
    parsed = parse_workflow_file(WORKFLOWS / "whatapi-otp.json")
    assert parsed is not None
    assert parsed.template_name == "otp"
    assert body_parameter_count(parsed.template_variables) == 1


def test_parse_all_workflows_produces_no_empty_webhook_paths():
    report = parse_workflows_dir(WORKFLOWS)
    assert len(report.services) >= 60
    assert all(s.webhook_path for s in report.services)
