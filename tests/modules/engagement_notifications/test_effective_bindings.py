"""Tests for effective engagement notification bindings API."""

from __future__ import annotations

import json

from datetime import date

import pytest
from sqlalchemy import text

from modules.engagement_notifications.effective import list_effective_for_engagement
from modules.engagements.models import Engagement
from tests.modules.notifications.notification_test_seeds import upsert_notification_service


@pytest.mark.asyncio
async def test_effective_merges_global_and_engagement_override(test_db_session):
    engagement_id = 88001
    await upsert_notification_service(
        test_db_session, service_key="welcome-whatsapp", channel="whatsapp"
    )
    await upsert_notification_service(
        test_db_session, service_key="welcome-email", channel="email"
    )
    test_db_session.add(
        Engagement(
            engagement_id=engagement_id,
            engagement_name="Effective Notify Test",
            organization_id=None,
            engagement_code="EFF88001",
            engagement_type=1,
            city="BLR",
            slot_duration=20,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 1),
            status="running",
        )
    )
    await test_db_session.flush()
    await test_db_session.execute(
        text(
            """
            INSERT INTO notification_events
                (event_code, event_name, recipient_type, notification_services, is_active)
            VALUES
                ('onboarding.completed', 'Onboarding', 'participant', CAST(:svc AS jsonb), true)
            ON CONFLICT (event_code, recipient_type) DO UPDATE SET
                notification_services = EXCLUDED.notification_services
            """
        ),
        {"svc": json.dumps(["welcome-whatsapp"])},
    )
    await test_db_session.execute(
        text(
            """
            INSERT INTO engagement_notifications
                (engagement_id, event_code, recipient_type, notification_services)
            VALUES
                (:eid, 'onboarding.completed', 'participant', CAST(:svc AS jsonb))
            """
        ),
        {"eid": engagement_id, "svc": json.dumps([{"service_key": "welcome-email"}])},
    )
    await test_db_session.commit()

    rows = await list_effective_for_engagement(test_db_session, engagement_id)
    participant = next(
        r
        for r in rows
        if r.event_code == "onboarding.completed" and r.recipient_type == "participant"
    )
    assert participant.source == "engagement"
    assert participant.notification_services[0].service_key == "welcome-email"
