"""Build dispatch payloads from engine event payloads."""

from __future__ import annotations

import json
from typing import Any

from modules.notifications.models import NotificationService
from modules.notifications.schemas import DispatchRequest, SessionDetails


def _template_needs_key(service: NotificationService, key: str) -> bool:
    raw = service.template_variables
    if raw is None:
        return False
    try:
        blob = json.dumps(raw)
    except (TypeError, ValueError):
        blob = str(raw)
    return f"{{{{{key}}}}}" in blob or key in blob


def service_needs_blood_report_url(service: NotificationService) -> bool:
    return _template_needs_key(service, "blood_report_url")


def service_needs_bio_ai_report_url(service: NotificationService) -> bool:
    return _template_needs_key(service, "bio_ai_report_url")


def service_needs_otp(service: NotificationService) -> bool:
    return _template_needs_key(service, "otp")


def service_needs_participant_detail(service: NotificationService) -> bool:
    return _template_needs_key(service, "participant_details") or _template_needs_key(
        service, "first_name"
    )


def service_needs_session_details(service: NotificationService) -> bool:
    return _template_needs_key(service, "session_details")


def service_needs_external_link(service: NotificationService) -> bool:
    return _template_needs_key(service, "external_link")


def build_dispatch_request(
    *,
    service_key: str,
    user_ids: list[int],
    payload: dict[str, Any],
    engagement_id: int | None,
    external_link: str | None = None,
) -> DispatchRequest:
    session_details = payload.get("session_details")
    parsed_session: SessionDetails | None = None
    if isinstance(session_details, SessionDetails):
        parsed_session = session_details
    elif isinstance(session_details, dict):
        parsed_session = SessionDetails.model_validate(session_details)

    session_by_user = payload.get("session_details_by_user_id")
    parsed_by_user: dict[int, SessionDetails] | None = None
    if isinstance(session_by_user, dict):
        parsed_by_user = {
            int(uid): SessionDetails.model_validate(details)
            for uid, details in session_by_user.items()
            if details is not None
        }

    return DispatchRequest(
        service_key=service_key,
        user_ids=user_ids,
        engagement_id=engagement_id,
        assessment_instance_id=payload.get("assessment_instance_id"),
        participant_details=payload.get("participant_details"),
        otp=payload.get("otp"),
        session_details=parsed_session,
        session_details_by_user_id=parsed_by_user,
        external_link=external_link or payload.get("external_link"),
    )
