"""E2E-style tests for bookings.* notification event code merge."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from modules.engagement_notifications.notification_setup import build_notification_setup_for_engagement
from modules.notifications.binding_resolver import BindingResolver
from modules.notifications.event_code_merge import apply_event_code_renames_async
from modules.notifications.events_catalog import map_legacy_event_code
from modules.webhooks.receiver.service import _PHLEBO_EVENT_CODES
from tests.helpers.engagement_types import engagement_type_id


async def _insert_home_blood_engagement(test_db_session, *, eid: int, etype: str = "bio_ai") -> int:
    type_id = await engagement_type_id(test_db_session, etype)
    await test_db_session.execute(
        text(
            """
            INSERT INTO engagements (
                engagement_id, engagement_name, engagement_code, engagement_type,
                assessment_package_id, diagnostic_package_id, city, slot_duration,
                start_date, end_date, status, blood_collection_type, payment_type
            )
            VALUES (
                :eid, 'Merge E2E', :code, :etype, 1, 1, 'BLR', 20,
                CURRENT_DATE, CURRENT_DATE + 1, 1, 'home_collection', 'paid_by_patient'
            )
            ON CONFLICT (engagement_id) DO NOTHING
            """
        ),
        {"eid": eid, "code": f"ME{eid}", "etype": type_id},
    )
    return type_id


@pytest.mark.asyncio
async def test_migration_renames_engagement_and_global_bindings(test_db_session):
    eid = 991001
    await _insert_home_blood_engagement(test_db_session, eid=eid)
    svc = json.dumps([{"service_key": "confirm-home-wa", "external_link": None}])
    await test_db_session.execute(
        text(
            """
            INSERT INTO engagement_notifications (
                engagement_id, event_code, event_name, recipient_type, delivery_channel,
                notification_services, condition_key
            )
            VALUES (
                :eid, 'bookings.confirmed', 'Booking confirmed', 'user', 'whatsapp',
                CAST(:svc AS jsonb), 'default'
            )
            """
        ),
        {"eid": eid, "svc": svc},
    )
    await test_db_session.execute(
        text(
            """
            INSERT INTO notification_events (
                event_code, event_name, recipient_type, delivery_channel,
                notification_services, engagement_type_id, condition_key
            )
            VALUES (
                'consultations.booked', 'Consultation booked', 'user', 'whatsapp',
                CAST(:svc AS jsonb), NULL, 'default'
            )
            ON CONFLICT ON CONSTRAINT uq_notification_events_binding DO NOTHING
            """
        ),
        {"svc": svc},
    )
    await test_db_session.commit()

    await apply_event_code_renames_async(test_db_session)
    await test_db_session.commit()

    row = (
        await test_db_session.execute(
            text(
                "SELECT event_code FROM engagement_notifications "
                "WHERE engagement_id = :eid LIMIT 1"
            ),
            {"eid": eid},
        )
    ).scalar_one()
    assert row == "bookings.blood_test.confirmed"

    global_code = (
        await test_db_session.execute(
            text(
                "SELECT event_code FROM notification_events "
                "WHERE event_code = 'bookings.consultation.booked' LIMIT 1"
            )
        )
    ).scalar_one_or_none()
    assert global_code == "bookings.consultation.booked"


@pytest.mark.asyncio
async def test_legacy_emit_resolves_migrated_engagement_slot(test_db_session):
    eid = 991002
    await _insert_home_blood_engagement(test_db_session, eid=eid)
    svc = json.dumps([{"service_key": "phlebo-assigned-whatsapp", "external_link": None}])
    await test_db_session.execute(
        text(
            """
            INSERT INTO engagement_notifications (
                engagement_id, event_code, event_name, recipient_type, delivery_channel,
                notification_services, condition_key
            )
            VALUES (
                :eid, 'bookings.blood_test.phlebo_assigned', 'Phlebo assigned', 'user', 'whatsapp',
                CAST(:svc AS jsonb), 'default'
            )
            """
        ),
        {"eid": eid, "svc": svc},
    )
    await test_db_session.commit()

    resolver = BindingResolver()
    bindings = await resolver.resolve(
        test_db_session,
        event_code="bookings.phlebo_assigned",
        engagement_id=eid,
        context={},
    )
    assert len(bindings) == 1
    assert bindings[0].notification_services[0]["service_key"] == "phlebo-assigned-whatsapp"


def test_healthians_phlebo_maps_to_blood_test_codes():
    assert _PHLEBO_EVENT_CODES["phlebo_assigned"] == "bookings.blood_test.phlebo_assigned"
    assert map_legacy_event_code("consultations.booked") == "bookings.consultation.booked"


@pytest.mark.asyncio
async def test_notification_setup_consultation_booked_is_applicable_not_extra(test_db_session):
    eid = 991003
    await _insert_home_blood_engagement(test_db_session, eid=eid, etype="bio_ai_with_consultation")
    await test_db_session.execute(
        text(
            """
            UPDATE engagements
            SET consultation_mode = 'online', payment_type = 'paid_by_group'
            WHERE engagement_id = :eid
            """
        ),
        {"eid": eid},
    )
    await test_db_session.commit()

    setup = await build_notification_setup_for_engagement(test_db_session, eid)
    booked = next((e for e in setup["events"] if e["event_code"] == "bookings.consultation.booked"), None)
    assert booked is not None
    assert booked["is_applicable"] is True
    assert booked["is_extra"] is False