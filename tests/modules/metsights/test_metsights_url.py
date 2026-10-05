"""Tests for MetSights external URL builder."""

from core.config import settings
from modules.metsights.client import _metsights_url


def test_metsights_url_external_prefix_and_trailing_slash(monkeypatch):
    monkeypatch.setattr(settings, "METSIGHTS_BASE_URL", "https://api.metsights.com")
    assert _metsights_url("profiles") == "https://api.metsights.com/external/profiles/"
    assert _metsights_url("records/ABC/vitals") == "https://api.metsights.com/external/records/ABC/vitals/"


def test_metsights_url_engagement_register_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "METSIGHTS_BASE_URL", "https://api.metsights.com")
    assert (
        _metsights_url("engagements/01a01348-24b6-0cfe-7db1-947da7056463/register")
        == "https://api.metsights.com/engagements/01a01348-24b6-0cfe-7db1-947da7056463/register/"
    )
