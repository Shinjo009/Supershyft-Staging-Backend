"""Tests for external API record assessment type normalization."""

from modules.metsights.sync_service import _normalize_metsights_type_code


def test_normalize_type_code_from_subscription_assessment():
    row = {
        "subscription": {
            "assessment": {
                "assessment_type_code": "2",
                "name": "MetSights Pro",
            }
        }
    }
    assert _normalize_metsights_type_code(row) == "2"


def test_normalize_type_code_legacy_assessment_code():
    assert _normalize_metsights_type_code({"assessment_code": "MET_BASIC"}) == "1"
