"""Back-compat: CBTW rows now live in report_sent_backfill_data (engagement_id 16)."""

from __future__ import annotations

from modules.notifications.report_sent_backfill_data import BACKFILL_COHORTS

CBTW_REGISTRATION_ROWS: list[dict] = next(
    (c["rows"] for c in BACKFILL_COHORTS if int(c["engagement_id"]) == 16),
    [],
)
