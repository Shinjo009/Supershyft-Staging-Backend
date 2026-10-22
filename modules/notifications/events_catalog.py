"""Hardcoded notification event catalog for rebuild (prompt 1).

Read-only source of truth for event_code, recipient types, and template variables.
Platform bindings in table ``notification_events`` reference these codes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EventType = Literal["api", "scheduled", "emergency"]

RECIPIENT_TYPES: frozenset[str] = frozenset({
    "participant",
    "admin",
    "inferior_admin",
    "partner",
    "partner_role",
    "onboarding_assistant",
})

LEGACY_MIGRATION_EVENT_CODES: frozenset[str] = frozenset({
    "onboarding",
    "pretest_guidelines",
    "questionnaire_reminder_before",
    "questionnaire_reminder_after",
    "blood_report_ready",
    "bioai_report_ready",
    "consultation_ready",
    "consultation_remainder",
    "consultation_booking_alert",
    "booking_guide",
    "report_ready",
})


@dataclass(frozen=True)
class CatalogVariable:
    key: str
    label: str
    description: str | None = None


@dataclass(frozen=True)
class CatalogEvent:
    event_code: str
    event_name: str
    event_type: EventType
    allowed_recipient_types: tuple[str, ...]
    variables: tuple[CatalogVariable, ...] = ()
    is_active: bool = True


def _base_contact_vars() -> tuple[CatalogVariable, ...]:
    return (
        CatalogVariable("first_name", "First name"),
        CatalogVariable("last_name", "Last name"),
        CatalogVariable("phone", "Phone"),
        CatalogVariable("email", "Email"),
    )


def _session_vars() -> tuple[CatalogVariable, ...]:
    return (
        CatalogVariable("session_details.date", "Session date"),
        CatalogVariable("session_details.slot", "Session slot"),
        CatalogVariable("session_details.cabin", "Cabin"),
        CatalogVariable("session_details.want", "Want flag"),
        CatalogVariable("session_details.expert_type", "Expert type"),
    )


def _phlebo_vars() -> tuple[CatalogVariable, ...]:
    return (
        CatalogVariable("participant_details.phlebo_name", "Phlebotomist name"),
        CatalogVariable("participant_details.masked_number", "Masked phone"),
        CatalogVariable("participant_details.tracking_url", "Tracking URL"),
        CatalogVariable("participant_details.eta_in_minutes", "ETA (minutes)"),
    )


def _gift_vars() -> tuple[CatalogVariable, ...]:
    return (
        CatalogVariable("participant_details.booker_name", "Booker name"),
        CatalogVariable("participant_details.recipient_name", "Recipient name"),
        CatalogVariable("participant_details.relationship", "Relationship"),
        CatalogVariable("participant_details.gift_url", "Gift URL"),
    )


def _ticket_vars() -> tuple[CatalogVariable, ...]:
    return (
        CatalogVariable("participant_details.name", "Contact name"),
        CatalogVariable("participant_details.query_text", "Query text"),
        CatalogVariable("participant_details.ticket_id", "Ticket ID"),
    )


def _evt(
    code: str,
    name: str,
    event_type: EventType,
    recipients: tuple[str, ...],
    extra_vars: tuple[CatalogVariable, ...] = (),
    *,
    is_active: bool = True,
) -> CatalogEvent:
    vars_set: dict[str, CatalogVariable] = {v.key: v for v in _base_contact_vars()}
    for v in extra_vars:
        vars_set[v.key] = v
    return CatalogEvent(
        event_code=code,
        event_name=name,
        event_type=event_type,
        allowed_recipient_types=recipients,
        variables=tuple(vars_set.values()),
        is_active=is_active,
    )


_CATALOG: tuple[CatalogEvent, ...] = (
    # Legacy engagement lifecycle (migrations 0107, 0114, 0119)
    _evt("onboarding", "Onboarding Notification", "api", ("onboarding_assistant", "partner"), _session_vars()),
    _evt("pretest_guidelines", "Pretest Guidelines", "scheduled", ("participant",), _session_vars()),
    _evt(
        "questionnaire_reminder_before",
        "Questionnaire Reminder (Before)",
        "scheduled",
        ("participant",),
    ),
    _evt(
        "questionnaire_reminder_after",
        "Questionnaire Reminder (After)",
        "scheduled",
        ("participant",),
    ),
    _evt(
        "blood_report_ready",
        "Blood Report Ready",
        "scheduled",
        ("participant",),
        (CatalogVariable("blood_report_url", "Blood report URL"),),
    ),
    _evt(
        "bioai_report_ready",
        "Bio-AI Report Ready",
        "scheduled",
        ("participant",),
        (CatalogVariable("bio_ai_report_url", "Bio-AI report URL"),),
    ),
    _evt(
        "consultation_ready",
        "Consultation Ready",
        "scheduled",
        ("participant",),
        (CatalogVariable("external_link", "Booking link"),),
    ),
    _evt("consultation_remainder", "Consultation Remainder", "scheduled", ("participant",), _session_vars()),
    _evt(
        "consultation_booking_alert",
        "Consultation Booking Alert",
        "api",
        ("onboarding_assistant", "partner_role"),
        _session_vars(),
    ),
    _evt("booking_guide", "Booking Guide", "scheduled", ("partner_role",), _session_vars()),
    _evt(
        "report_ready",
        "Report Ready",
        "api",
        ("participant",),
        (
            CatalogVariable("blood_report_url", "Blood report URL"),
            CatalogVariable("bio_ai_report_url", "Bio-AI report URL"),
        ),
    ),
    # Auth / users
    _evt("otp_whatsapp", "OTP WhatsApp", "api", ("participant",), (CatalogVariable("otp", "OTP code"),)),
    _evt("otp_email", "OTP Email", "api", ("participant",), (CatalogVariable("otp", "OTP code"),)),
    _evt("user_registered", "User Registered", "api", ("participant", "admin")),
    _evt("user_onboarded", "User Onboarded", "api", ("participant", "onboarding_assistant")),
    _evt("family_onboard_started", "Family Onboard Started", "api", ("participant",), _gift_vars()),
    _evt(
        "family_onboard_payment_confirmed",
        "Family Onboard Payment Confirmed",
        "api",
        ("participant",),
        _gift_vars(),
    ),
    _evt(
        "family_onboard_member_registered",
        "Family Onboard Member Registered",
        "api",
        ("participant",),
        _gift_vars(),
    ),
    # Bookings / consultations
    _evt(
        "consultation_booked",
        "Consultation Booked",
        "api",
        ("participant", "onboarding_assistant"),
        _session_vars(),
    ),
    _evt(
        "consultation_rescheduled",
        "Consultation Rescheduled",
        "api",
        ("participant",),
        _session_vars(),
    ),
    _evt(
        "blood_test_rescheduled",
        "Blood Test Rescheduled",
        "api",
        ("participant",),
        _session_vars(),
    ),
    _evt("blood_test_cancelled", "Blood Test Cancelled", "api", ("participant",), _session_vars()),
    _evt("bio_ai_booking_cancelled", "Bio-AI Booking Cancelled", "api", ("participant",)),
    _evt(
        "support_query_raised",
        "Support Query Raised",
        "api",
        ("onboarding_assistant", "admin"),
        _ticket_vars(),
    ),
    # Engagements (inactive until prompt 3)
    _evt(
        "engagement_created",
        "Engagement Created",
        "api",
        ("admin", "onboarding_assistant"),
        is_active=False,
    ),
    _evt(
        "engagement_updated",
        "Engagement Updated",
        "api",
        ("admin", "onboarding_assistant"),
        is_active=False,
    ),
    _evt(
        "participants_assigned_batch",
        "Participants Assigned (Batch)",
        "api",
        ("participant", "onboarding_assistant"),
        is_active=False,
    ),
    # Webhooks
    _evt(
        "healthians_booking_confirmed",
        "Healthians Booking Confirmed",
        "api",
        ("participant",),
        _session_vars(),
    ),
    _evt(
        "healthians_phlebo_assigned",
        "Healthians Phlebo Assigned",
        "api",
        ("participant",),
        _phlebo_vars() + _session_vars(),
    ),
    _evt(
        "healthians_phlebo_reassigned",
        "Healthians Phlebo Reassigned",
        "api",
        ("participant",),
        _phlebo_vars() + _session_vars(),
    ),
    _evt(
        "healthians_phlebo_enroute",
        "Healthians Phlebo En Route",
        "api",
        ("participant",),
        _phlebo_vars(),
    ),
    _evt(
        "healthians_phlebo_delay",
        "Healthians Phlebo Delay",
        "api",
        ("participant",),
        _phlebo_vars(),
    ),
    _evt(
        "aurae_report_ready",
        "Aurae Report Ready",
        "api",
        ("participant",),
        (CatalogVariable("external_link", "Report link"),),
    ),
    _evt(
        "orange_health_webhook_received",
        "Orange Health Webhook Received",
        "api",
        ("admin",),
        is_active=False,
    ),
    # Emergency
    _evt("cpu_above_threshold", "CPU Above Threshold", "emergency", ("admin",)),
    _evt(
        "notification_delivery_failures",
        "Notification Delivery Failures",
        "emergency",
        ("admin",),
        is_active=False,
    ),
)

_CATALOG_BY_CODE: dict[str, CatalogEvent] = {e.event_code: e for e in _CATALOG}


def get_events_catalog() -> list[dict]:
    """Serialize full catalog for API responses."""
    return [catalog_event_to_dict(e) for e in _CATALOG]


def catalog_event_to_dict(event: CatalogEvent) -> dict:
    return {
        "event_code": event.event_code,
        "event_name": event.event_name,
        "event_type": event.event_type,
        "allowed_recipient_types": list(event.allowed_recipient_types),
        "variables": [
            {"key": v.key, "label": v.label, "description": v.description}
            for v in event.variables
        ],
        "is_active": event.is_active,
    }


def get_catalog_event(event_code: str) -> CatalogEvent | None:
    return _CATALOG_BY_CODE.get(event_code)


def validate_event_binding(event_code: str, recipient_type: str) -> CatalogEvent:
    """Return catalog entry or raise ValueError with a stable message."""
    event = get_catalog_event(event_code)
    if event is None:
        raise ValueError(f"Unknown event_code: {event_code}")
    if recipient_type not in RECIPIENT_TYPES:
        raise ValueError(f"Unknown recipient_type: {recipient_type}")
    if recipient_type not in event.allowed_recipient_types:
        raise ValueError(
            f"recipient_type '{recipient_type}' is not allowed for event '{event_code}'"
        )
    return event
