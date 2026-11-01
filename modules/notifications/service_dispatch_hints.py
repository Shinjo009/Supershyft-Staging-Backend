"""Post-cutover dispatch validation helpers (require_* columns removed)."""

from __future__ import annotations

import json

from modules.notifications.models import NotificationService

OTP_SERVICE_KEYS = frozenset({"whatapi-otp", "email-otp"})


def _vars_blob(svc: NotificationService) -> str:
    try:
        return json.dumps(svc.template_variables or "").lower()
    except (TypeError, ValueError):
        return ""


def service_needs_otp(svc: NotificationService) -> bool:
    if svc.service_key in OTP_SERVICE_KEYS:
        return True
    return "otp" in _vars_blob(svc)


def service_needs_participant_detail(svc: NotificationService) -> bool:
    blob = _vars_blob(svc)
    return "participant_detail" in blob or "participant_details" in blob


def service_needs_session_details(svc: NotificationService) -> bool:
    return "session_details" in _vars_blob(svc)


def service_needs_external_link(svc: NotificationService) -> bool:
    return "external_link" in _vars_blob(svc)


def service_needs_blood_report(svc: NotificationService) -> bool:
    blob = _vars_blob(svc)
    return "blood_report" in blob


def service_needs_bio_ai_report(svc: NotificationService) -> bool:
    blob = _vars_blob(svc)
    return "bio_ai" in blob or "bioai" in blob
