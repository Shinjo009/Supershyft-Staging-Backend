"""Tests for Orange Health cancel partner body helpers."""

from __future__ import annotations

from modules.diagnostics.orange_health.cancel_helpers import build_orange_cancel_partner_body


def test_cancel_body_duplicates_remarks_into_explanation_when_empty():
    body = build_orange_cancel_partner_body(cancellation_reason="TESTING PROD")
    assert body == {
        "cancellationReason": "TESTING PROD",
        "cancellationExplanation": "TESTING PROD",
    }


def test_cancel_body_keeps_distinct_explanation_when_provided():
    body = build_orange_cancel_partner_body(
        cancellation_reason="Any Reason",
        cancellation_explanation="Customer changed plans",
    )
    assert body["cancellationReason"] == "Any Reason"
    assert body["cancellationExplanation"] == "Customer changed plans"