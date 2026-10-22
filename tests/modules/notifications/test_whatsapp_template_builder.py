"""Tests for template variable resolution."""

from __future__ import annotations

from modules.notifications.template_variables import resolve_text


def test_resolve_text_placeholder():
    ctx = {"first_name": "Alex", "session_details": {"date": "2024-01-01"}}
    assert resolve_text("{{first_name}}", ctx) == "Alex"
    assert resolve_text("Date: {{session_details.date}}", ctx) == "Date: 2024-01-01"
