"""Build platform notification_events fixture from staging snapshot + catalog gaps."""

from __future__ import annotations

import json
from pathlib import Path

from modules.notifications.event_recipient_defaults import DEFAULT_RECIPIENT_TYPE_BY_EVENT
from modules.notifications.events_catalog import LEGACY_MIGRATION_EVENT_CODES, get_catalog_event

REPO = Path(__file__).resolve().parents[1]
STAGING = REPO / "db" / "fixtures" / "notification_snapshot_staging.json"
OUT = REPO / "db" / "fixtures" / "notification_events_platform_defaults.json"

# Platform defaults when not present in staging snapshot (service keys must exist in DB).
_EXTRA_BINDINGS: dict[str, list[str]] = {
    "questionnaire_reminder_after": ["questionnaire-reminder-supershyft"],
    "consultation_ready": ["book-doctor-consultation-whatsapp", "book-doctor-consultation-email"],
    "consultation_remainder": ["consultation-remainder-whatsapp", "consultation-remainder-email"],
    "booking_guide": ["send-phlebo-booking-guide-whatsapp", "send-expert-consultation-guide-whatsapp"],
}


def main() -> None:
    staging = json.loads(STAGING.read_text(encoding="utf-8"))
    by_key: dict[tuple[str, str], dict] = {}
    for row in staging.get("events", []):
        key = (row["event_code"], row["recipient_type"])
        by_key[key] = {
            "event_code": row["event_code"],
            "event_name": row["event_name"],
            "recipient_type": row["recipient_type"],
            "notification_services": row["notification_services"],
        }

    for event_code in LEGACY_MIGRATION_EVENT_CODES:
        recipient = DEFAULT_RECIPIENT_TYPE_BY_EVENT.get(event_code, "participant")
        key = (event_code, recipient)
        if key in by_key:
            continue
        services = _EXTRA_BINDINGS.get(event_code)
        if not services:
            continue
        cat = get_catalog_event(event_code)
        by_key[key] = {
            "event_code": event_code,
            "event_name": cat.event_name if cat else event_code,
            "recipient_type": recipient,
            "notification_services": [{"service_key": sk} for sk in services],
        }

    out = [by_key[k] for k in sorted(by_key)]
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}: {len(out)} bindings")


if __name__ == "__main__":
    main()
