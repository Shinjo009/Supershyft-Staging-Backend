"""Auto booking must not be enabled with camp blood collection."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from modules.engagements.enums import EngagementPaymentType
from modules.engagements.models import BloodCollectionType
from modules.engagements.schemas import EngagementCreateRequest


def _minimal_create(**overrides):
    base = {
        "organization_id": 1,
        "engagement_type": 1,
        "slot_duration": 60,
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "payment_type": EngagementPaymentType.paid_by_group,
        "auto_booking": False,
        "blood_collection_type": BloodCollectionType.home_collection,
    }
    base.update(overrides)
    return EngagementCreateRequest(**base)


def test_auto_booking_allowed_for_home_collection():
    req = _minimal_create(auto_booking=True, blood_collection_type=BloodCollectionType.home_collection)
    assert req.auto_booking is True


def test_auto_booking_rejected_for_camp_collection():
    with pytest.raises(ValidationError) as exc:
        _minimal_create(auto_booking=True, blood_collection_type=BloodCollectionType.camp_collection)
    assert "camp collection" in str(exc.value).lower()
