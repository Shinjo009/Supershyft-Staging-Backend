"""Per-service engagement binding maintenance."""

from __future__ import annotations

import pytest

from modules.engagement_notifications.repository import EngagementNotificationsRepository
from modules.engagement_notifications.service_config import (
    NotificationServiceConfigItem,
    normalize_notification_services,
    replace_or_merge_service_config,
    serialize_for_db,
)


def test_replace_or_merge_service_config_updates_one_key():
    prior = [
        NotificationServiceConfigItem(service_key="a"),
        NotificationServiceConfigItem(service_key="b"),
    ]
    incoming = [NotificationServiceConfigItem(service_key="b", external_link="https://example.com")]
    merged = replace_or_merge_service_config(prior, incoming)
    assert [c.service_key for c in merged] == ["a", "b"]
    assert merged[1].external_link == "https://example.com"


def test_replace_or_merge_service_config_appends_new_key():
    prior = [NotificationServiceConfigItem(service_key="a")]
    incoming = [NotificationServiceConfigItem(service_key="c")]
    merged = replace_or_merge_service_config(prior, incoming)
    assert [c.service_key for c in merged] == ["a", "c"]


@pytest.mark.asyncio
async def test_remove_service_from_slot_deletes_empty_slot(test_db_session):
    from sqlalchemy import text

    eid = 88077
    await test_db_session.execute(
        text(
            """
            INSERT INTO engagements (
                engagement_id, engagement_name, engagement_code, engagement_type,
                assessment_package_id, diagnostic_package_id, city, slot_duration,
                start_date, end_date, status, blood_collection_type, payment_type
            )
            VALUES (
                :eid, 'Svc Remove', 'E2E88077', 1, 1, 1, 'BLR', 20,
                '2026-12-01', '2026-12-01', 3, 'camp_collection', 'paid_by_group'
            )
            ON CONFLICT (engagement_id) DO NOTHING
            """
        ),
        {"eid": eid},
    )
    repo = EngagementNotificationsRepository()
    row = await repo.upsert_binding_slot(
        test_db_session,
        engagement_id=eid,
        event_code="users.onboarded",
        recipient_type="user",
        delivery_channel="whatsapp",
        notification_services=serialize_for_db(
            [
                NotificationServiceConfigItem(service_key="only-one"),
            ]
        ),
        event_name="Onboarded",
    )
    await test_db_session.flush()
    removed = await repo.remove_service_from_slot(test_db_session, row.id, "only-one")
    assert removed is True
    assert await repo.get_slot_by_id(test_db_session, row.id) is None


@pytest.mark.asyncio
async def test_remove_service_from_slot_keeps_sibling_services(test_db_session):
    from sqlalchemy import text

    eid = 88078
    await test_db_session.execute(
        text(
            """
            INSERT INTO engagements (
                engagement_id, engagement_name, engagement_code, engagement_type,
                assessment_package_id, diagnostic_package_id, city, slot_duration,
                start_date, end_date, status, blood_collection_type, payment_type
            )
            VALUES (
                :eid, 'Svc Remove 2', 'E2E88078', 1, 1, 1, 'BLR', 20,
                '2026-12-01', '2026-12-01', 3, 'camp_collection', 'paid_by_group'
            )
            ON CONFLICT (engagement_id) DO NOTHING
            """
        ),
        {"eid": eid},
    )
    repo = EngagementNotificationsRepository()
    row = await repo.upsert_binding_slot(
        test_db_session,
        engagement_id=eid,
        event_code="reports.bioai_ready",
        recipient_type="user",
        delivery_channel="whatsapp",
        notification_services=serialize_for_db(
            [
                NotificationServiceConfigItem(service_key="wa-a"),
                NotificationServiceConfigItem(service_key="wa-b"),
            ]
        ),
        event_name="BioAI",
    )
    await test_db_session.flush()
    removed = await repo.remove_service_from_slot(test_db_session, row.id, "wa-a")
    assert removed is True
    slot = await repo.get_slot_by_id(test_db_session, row.id)
    assert slot is not None
    keys = [c.service_key for c in normalize_notification_services(slot.notification_services)]
    assert keys == ["wa-b"]