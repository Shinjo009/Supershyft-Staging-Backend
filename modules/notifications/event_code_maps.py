"""Healthians phlebo webhook event_type → catalog event_code."""

from __future__ import annotations

HEALTHIANS_PHLEBO_EVENT_TO_CATALOG: dict[str, str] = {
    "phlebo_assigned": "collection.phlebo.assigned",
    "phlebo_reassigned": "collection.phlebo.reassigned",
    "phlebo_enroute": "collection.phlebo.enroute",
    "phlebo_delay_notification": "collection.phlebo.delayed",
}


def catalog_event_for_phlebo_webhook(event_type: str) -> str | None:
    return HEALTHIANS_PHLEBO_EVENT_TO_CATALOG.get(str(event_type or "").strip())
