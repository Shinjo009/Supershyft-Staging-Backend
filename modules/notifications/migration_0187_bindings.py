"""Data migration helpers for Alembic 0187 event bindings."""

from __future__ import annotations

import json
from typing import Any

from modules.notifications.events_catalog import LEGACY_EVENT_CODE_MAP

# Default recipient when engagement row has no recipient_type (Prompt 4 table + catalog).
EVENT_DEFAULT_RECIPIENT: dict[str, str] = {
    "onboarding.completed": "oa.all",
    "collection.reminder.pretest": "participant",
    "collection.reminder.booking_guide": "oa.phlebo",
    "assessment.reminder.before": "participant",
    "assessment.reminder.after": "participant",
    "report.blood.ready": "participant",
    "report.bioai.ready": "participant",
    "report.vifc.ready": "participant",
    "consultation.ready": "participant",
    "consultation.reminder": "participant",
    "consultation.booked": "oa.expert",
    "collection.confirmed": "participant",
    "collection.phlebo.assigned": "participant",
    "collection.phlebo.reassigned": "participant",
    "collection.phlebo.enroute": "participant",
    "collection.phlebo.delayed": "participant",
    "payment.gift.sent.booker": "booker",
    "payment.gift.sent.member": "family_member",
    "auth.otp.sent": "participant",
    "support.ticket.created": "admin",
    "system.cpu.alert": "admin",
}


def map_legacy_event_code(code: str) -> str:
    raw = (code or "").strip()
    if not raw:
        return raw
    return LEGACY_EVENT_CODE_MAP.get(raw, raw)


def default_recipient_for_event(event_code: str) -> str:
    mapped = map_legacy_event_code(event_code)
    return EVENT_DEFAULT_RECIPIENT.get(mapped, "participant")


def extract_service_keys_from_json(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    keys: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            key = item.strip()
        elif isinstance(item, dict):
            key = str(item.get("service_key") or "").strip()
        else:
            continue
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def merge_service_keys(existing: list[str], new_keys: list[str]) -> list[str]:
    merged = list(existing)
    seen = set(existing)
    for key in new_keys:
        if key not in seen:
            seen.add(key)
            merged.append(key)
    return merged


def services_json_for_keys(keys: list[str]) -> str:
    return json.dumps([{"service_key": k} for k in keys])
