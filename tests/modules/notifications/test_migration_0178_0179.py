"""Schema checks after notification event migrations."""

from __future__ import annotations

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_legacy_event_tables_dropped(test_db_session):
    for table in ("auto_notification_events", "engagement_notification_defaults"):
        row = await test_db_session.execute(
            text(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = :name
                """
            ),
            {"name": table},
        )
        assert row.scalar() is None


@pytest.mark.asyncio
async def test_engagement_notifications_has_event_code(test_db_session):
    row = await test_db_session.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'engagement_notifications'
              AND column_name = 'event_code'
            """
        )
    )
    assert row.scalar() == "event_code"
