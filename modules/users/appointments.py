"""User-facing appointment list helpers (consultations + blood tests)."""

from __future__ import annotations

from typing import Any, Literal

from modules.experts.consultations import (
    UserConsultationListStatus,
    _engagement_status_is_cancelled,
)

UserAppointmentListStatus = Literal["scheduled", "completed", "cancelled"]


def derive_user_consultation_appointment_status(
    *,
    done: bool,
    want: bool | None,
    engagement_status: Any,
) -> UserConsultationListStatus:
    """List status for consultations on GET /users/me/appointments (want=None counts as wanted)."""
    if _engagement_status_is_cancelled(engagement_status) or want is False:
        return "cancelled"
    if done:
        return "completed"
    if want is True or want is None:
        return "scheduled"
    return "cancelled"


def derive_user_blood_appointment_status(
    *,
    blood_row_status: str,
    engagement_status: Any,
    collected_at: Any,
) -> UserAppointmentListStatus:
    """List status for blood bookings on GET /users/me/appointments."""
    if _engagement_status_is_cancelled(engagement_status):
        return "cancelled"
    status_norm = (blood_row_status or "").lower()
    if status_norm == "cancelled":
        return "cancelled"
    if collected_at is not None:
        return "completed"
    if status_norm == "active":
        return "scheduled"
    return "cancelled"


__all__ = [
    "UserAppointmentListStatus",
    "derive_user_blood_appointment_status",
    "derive_user_consultation_appointment_status",
]
