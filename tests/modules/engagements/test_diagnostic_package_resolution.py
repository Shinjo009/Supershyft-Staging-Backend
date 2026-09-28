"""Package choice on engagements: unisex or a male and female pair."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from core.exceptions import AppError
from modules.engagements.diagnostic_package_resolution import resolve_diagnostic_package_id
from modules.engagements.schemas import EngagementCreateRequest


def _engagement(**kwargs):
    defaults = {
        "diagnostic_package_id": None,
        "diagnostic_package_id_male": None,
        "diagnostic_package_id_female": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_unisex_ignores_gender():
    engagement = _engagement(diagnostic_package_id=7)
    assert resolve_diagnostic_package_id(engagement, user_gender=None) == 7
    assert resolve_diagnostic_package_id(engagement, user_gender="female") == 7


def test_split_picks_gender_package():
    engagement = _engagement(diagnostic_package_id_male=17, diagnostic_package_id_female=24)
    assert resolve_diagnostic_package_id(engagement, user_gender="Female") == 24
    assert resolve_diagnostic_package_id(engagement, user_gender="M") == 17


def test_split_rejects_missing_gender():
    engagement = _engagement(diagnostic_package_id_male=17, diagnostic_package_id_female=24)
    with pytest.raises(AppError) as exc:
        resolve_diagnostic_package_id(engagement, user_gender="other")
    assert exc.value.error_code == "PARTICIPANT_GENDER_REQUIRED"


def test_create_rejects_mixed_or_partial_packages():
    base = {
        "organization_id": 1,
        "engagement_type": 1,
        "slot_duration": 30,
        "start_date": "2026-09-28",
        "end_date": "2026-09-28",
    }
    with pytest.raises(ValidationError):
        EngagementCreateRequest(**base, diagnostic_package_id=1, diagnostic_package_id_male=2, diagnostic_package_id_female=3)
    with pytest.raises(ValidationError):
        EngagementCreateRequest(**base, diagnostic_package_id_male=2)

    split = EngagementCreateRequest(
        **base,
        diagnostic_package_id_male=2,
        diagnostic_package_id_female=3,
    )
    assert split.diagnostic_package_id is None
    assert split.diagnostic_package_id_male == 2
