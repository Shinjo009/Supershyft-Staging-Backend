"""Ensure contact dispatch loads engagement template variables."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text

from modules.notifications.models import NotificationService
from modules.notifications.repository import NotificationsRepository
from modules.notifications.service import NotificationsService

from tests.modules.notifications.dispatch_mocks import patch_service_direct_deliver


async def _seed_engagement_with_consultations(test_db_session, *, engagement_id: int):
    from modules.engagements.models import Engagement

    test_db_session.add(
        Engagement(
            engagement_id=engagement_id,
            engagement_name="Camp X",
            engagement_code="CAMPX",
            engagement_type=None,
            assessment_package_id=1,
            diagnostic_package_id=1,
            city="BLR",
            slot_duration=20,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 2),
            status="running",
            consultations={"doctor": True, "nutrition": True},
        )
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_dispatch_to_contacts_resolves_engagement_id_in_literal_url(
    test_db_session, monkeypatch
):
    eid = 88001
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, assessment_type_code, status) "
            "VALUES (1, 'PKG', 'Pkg', '1', 1) ON CONFLICT (package_id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, reference_id, package_name, diagnostic_provider, status, bookings_count) "
            "VALUES (1, 'REF1', 'Diag', 'healthians', 1, 0) ON CONFLICT (diagnostic_package_id) DO NOTHING"
        )
    )
    await _seed_engagement_with_consultations(test_db_session, engagement_id=eid)

    service_key = "booking_guide_url_test"
    svc = NotificationService(
        service_key=service_key,
        display_name="Booking guide URL",
        channel="whatsapp",
        template_name="booking-guide",
        template_variables={
            "slots": [
                {
                    "index": 1,
                    "source": "literal",
                    "value": "https://admin.example/engagements/{{engagement.engagement_id}}/console",
                }
            ],
        },
        is_active=True,
    )
    test_db_session.add(svc)
    await test_db_session.commit()

    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)
    monkeypatch.setattr("modules.notifications.service.get_delivery_scheduler", lambda: type(
        "S", (), {"defer_enabled": False}
    )())

    notifications_service = NotificationsService(NotificationsRepository())
    await notifications_service.dispatch_to_contacts(
        test_db_session,
        service_key=service_key,
        contacts=[{"first_name": "Phlebo", "phone": "9876543210"}],
        engagement_id=eid,
        event_code="reminders.booking_guide",
    )

    assert deliver_calls
    members = deliver_calls[0]["members"]
    assert members[0]["engagement"]["engagement_id"] == str(eid)
    assert members[0]["engagement"]["consultation_types"] == "doctor and nutrition"

    from modules.notifications.context_builder import build_member_context
    from modules.notifications.template_variables import resolve_slots

    context = build_member_context(members[0])
    slots = resolve_slots(svc.template_variables, context)
    assert slots == [f"https://admin.example/engagements/{eid}/console"]
    assert "/engagements//" not in slots[0]