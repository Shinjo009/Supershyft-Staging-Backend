"""Participant payment eligibility for engagement features and cron jobs."""

from __future__ import annotations

from sqlalchemy import ColumnElement

from core.exceptions import AppError
from modules.engagements.enums import EngagementPaymentType
from modules.engagements.models import Engagement, EngagementParticipant


def engagement_payment_type_value(engagement: Engagement) -> str:
    payment_type = getattr(engagement, "payment_type", None)
    if payment_type is None:
        return EngagementPaymentType.paid_by_group.value
    return payment_type.value if hasattr(payment_type, "value") else str(payment_type)


def default_paid_for_enrollment(engagement: Engagement) -> bool:
    return engagement_payment_type_value(engagement) != EngagementPaymentType.paid_by_patient.value


def paid_participant_sql_filter() -> ColumnElement[bool]:
    return EngagementParticipant.paid.is_(True)


def ensure_participant_paid(participant: EngagementParticipant) -> None:
    if not bool(getattr(participant, "paid", True)):
        raise AppError(
            status_code=403,
            error_code="PAYMENT_REQUIRED",
            message="Participant payment is required before using this engagement feature",
        )
