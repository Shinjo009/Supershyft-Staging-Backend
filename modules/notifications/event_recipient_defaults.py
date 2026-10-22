"""Default recipient_type per event_code for engagement-level bindings and data migration."""

from __future__ import annotations

# Used when engagement_notifications row has services but no recipient_type column.
DEFAULT_RECIPIENT_TYPE_BY_EVENT: dict[str, str] = {
    "onboarding": "onboarding_assistant",
    "consultation_booking_alert": "onboarding_assistant",
    "booking_guide": "partner_role",
    "pretest_guidelines": "participant",
    "questionnaire_reminder_before": "participant",
    "questionnaire_reminder_after": "participant",
    "blood_report_ready": "participant",
    "bioai_report_ready": "participant",
    "consultation_ready": "participant",
    "consultation_remainder": "participant",
    "report_ready": "participant",
    "otp_whatsapp": "participant",
    "otp_email": "participant",
    "user_registered": "participant",
    "user_onboarded": "participant",
    "family_onboard_payment_confirmed": "participant",
    "support_query_raised": "onboarding_assistant",
    "consultation_booked": "participant",
    "consultation_rescheduled": "participant",
    "blood_test_rescheduled": "participant",
    "blood_test_cancelled": "participant",
    "healthians_booking_confirmed": "participant",
    "healthians_phlebo_assigned": "participant",
    "healthians_phlebo_reassigned": "participant",
    "healthians_phlebo_enroute": "participant",
    "healthians_phlebo_delay": "participant",
    "aurae_report_ready": "participant",
    "cpu_above_threshold": "admin",
}


def default_recipient_type_for_event(event_code: str, *, fallback: str = "participant") -> str:
    return DEFAULT_RECIPIENT_TYPE_BY_EVENT.get(event_code, fallback)
