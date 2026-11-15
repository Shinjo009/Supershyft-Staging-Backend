"""SQL helpers for notification module tests."""

from __future__ import annotations

from db.column_types import STATUS_ENGAGEMENT


def engagement_status_code(label: str) -> int:
    return int(STATUS_ENGAGEMENT[label])