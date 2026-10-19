"""Unit tests for participant payment eligibility."""

from __future__ import annotations

import pytest

from core.exceptions import AppError
from modules.engagements.enums import EngagementPaymentType
from modules.engagements.models import Engagement, EngagementParticipant
from modules.engagements.participant_eligibility import (
    default_paid_for_enrollment,
    ensure_participant_paid,
    engagement_payment_type_value,
)


def test_default_paid_for_enrollment():
    group = Engagement(payment_type=EngagementPaymentType.paid_by_group)
    patient = Engagement(payment_type=EngagementPaymentType.paid_by_patient)
    assert default_paid_for_enrollment(group) is True
    assert default_paid_for_enrollment(patient) is False


def test_ensure_participant_paid_raises_when_unpaid():
    participant = EngagementParticipant(paid=False)
    with pytest.raises(AppError) as exc:
        ensure_participant_paid(participant)
    assert exc.value.error_code == "PAYMENT_REQUIRED"


def test_engagement_payment_type_value_defaults():
    engagement = Engagement()
    engagement.payment_type = None
    assert engagement_payment_type_value(engagement) == EngagementPaymentType.paid_by_group.value
