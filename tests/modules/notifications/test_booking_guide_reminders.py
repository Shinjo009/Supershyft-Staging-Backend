"""Tests for booking guide reminder dispatch."""

from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import text

from modules.engagements.repository import EngagementsRepository
from modules.notifications.booking_guide_reminders import dispatch_booking_guide_reminders
from modules.notifications.repository import NotificationsRepository
from modules.notifications.service import NotificationsService
from tests.helpers.auth import seed_employee, seed_partner
from tests.modules.notifications.dispatch_mocks import patch_service_direct_deliver
from tests.modules.notifications.notification_event_seed import upsert_engagement_notification
from tests.modules.notifications.sql_helpers import engagement_status_code

BOOKING_GUIDE_WHATSAPP_KEY = "reminders-booking-guide-whatsapp-1"
BOOKING_GUIDE_EMAIL_KEY = "booking-guide-email"
DEFAULT_BOOKING_GUIDE_KEYS = f"{BOOKING_GUIDE_WHATSAPP_KEY},{BOOKING_GUIDE_EMAIL_KEY}"


async def _seed_dependencies(test_db_session) -> None:
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, status) "
            "VALUES (1, 'PKG1', 'Test Package', 1) ON CONFLICT (package_id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, package_name, diagnostic_provider, status) "
            "VALUES (1, 'Test Diagnostic', 'healthians', 1) ON CONFLICT (diagnostic_package_id) DO NOTHING"
        )
    )
    for service_key, channel, template_label in (
        (BOOKING_GUIDE_WHATSAPP_KEY, "whatsapp", "send-phlebo-booking-guide-whatsapp-v1"),
        (BOOKING_GUIDE_EMAIL_KEY, "email", "booking-guide-email"),
    ):
        await test_db_session.execute(
            text(
                "INSERT INTO notification_services "
                "(service_key, display_name, channel, template_name, email_subject, email_body, is_active, require_blood_report_url, "
                "require_bio_ai_report_url, require_participant_detail) "
                "VALUES (:sk, :dn, :ch, :template_name, :email_subject, :email_body, true, false, false, false) "
                "ON CONFLICT (service_key) DO UPDATE SET is_active = true"
            ),
            {
                "sk": service_key,
                "dn": service_key,
                "ch": channel,
                "template_name": template_label,
                "email_subject": "Test",
                "email_body": "Test",
            },
        )
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_types (code, display_name, is_active) "
            "VALUES ('bio_ai', 'BioAI', true) "
            "ON CONFLICT (code) DO UPDATE SET is_active = true"
        )
    )
    await test_db_session.commit()


async def _bind_booking_guide_services(
    test_db_session,
    *,
    engagement_id: int,
    service_keys: str = DEFAULT_BOOKING_GUIDE_KEYS,
    recipient_types: tuple[str, ...] = ("assistants.phlebo",),
) -> None:
    for recipient_type in recipient_types:
        await upsert_engagement_notification(
            test_db_session,
            engagement_id=engagement_id,
            event_code="reminders.booking_guide",
            service_keys=service_keys,
            recipient_type=recipient_type,
        )


async def _insert_engagement(
    test_db_session,
    *,
    engagement_id: int,
    engagement_code: str,
    status: str,
    start_date: str = "2026-06-01",
    end_date: str = "2026-06-30",
    slot_detail_id: int | None = None,
    bind_services: bool = True,
    service_keys: str = DEFAULT_BOOKING_GUIDE_KEYS,
    recipient_types: tuple[str, ...] = ("assistants.phlebo",),
) -> None:
    slot_value = "NULL" if slot_detail_id is None else str(slot_detail_id)
    await test_db_session.execute(
        text(
            "INSERT INTO engagements "
            "(engagement_id, engagement_name, engagement_code, engagement_type, assessment_package_id, "
            "diagnostic_package_id, city, slot_duration, start_date, end_date, status, organization_id, slot_detail_id) "
            f"VALUES ({engagement_id}, 'Camp {engagement_id}', '{engagement_code}', "
            "(SELECT id FROM engagement_types WHERE code = 'bio_ai'), 1, 1, 'BLR', 20, "
            f"'{start_date}', '{end_date}', {engagement_status_code(status)}, NULL, {slot_value})"
        )
    )
    if bind_services:
        await _bind_booking_guide_services(
            test_db_session,
            engagement_id=engagement_id,
            service_keys=service_keys,
            recipient_types=recipient_types,
        )


async def _insert_slot_detail(
    test_db_session,
    *,
    slot_detail_id: int,
    slot_detail: dict,
) -> None:
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_slot_info (slot_detail_id, slot_detail) "
            "VALUES (:sid, CAST(:detail AS jsonb))"
        ),
        {"sid": slot_detail_id, "detail": json.dumps(slot_detail)},
    )


async def _assign_partner(
    test_db_session,
    *,
    partner_id: int,
    engagement_id: int,
    role: str = "phlebo",
    phone: str | None = None,
) -> None:
    await seed_partner(
        test_db_session,
        partner_id=partner_id,
        role=role,
        name=f"Partner {partner_id}",
        phone=phone or f"9{partner_id:09d}"[:15],
        commit=False,
    )
    await test_db_session.execute(
        text(
            "INSERT INTO onboarding_assistant_assignment (partner_id, engagement_id) "
            "VALUES (:pid, :eid)"
        ),
        {"pid": partner_id, "eid": engagement_id},
    )


async def _assign_staff(
    test_db_session,
    *,
    employee_id: int,
    engagement_id: int,
    role: str = "admin",
    phone: str | None = None,
) -> None:
    await seed_employee(
        test_db_session,
        employee_id=employee_id,
        role=role,
        name=f"Staff {employee_id}",
        phone=phone or f"8{employee_id:09d}"[:15],
        commit=False,
    )
    await test_db_session.execute(
        text(
            "INSERT INTO onboarding_assistant_assignment (employee_id, engagement_id) "
            "VALUES (:eid_emp, :eid)"
        ),
        {"eid_emp": employee_id, "eid": engagement_id},
    )


def _services():
    notifications_repository = NotificationsRepository()
    return (
        NotificationsService(notifications_repository),
        EngagementsRepository(),
    )


@pytest.mark.asyncio
async def test_booking_guide_reminders_dispatch_to_phlebo_and_staff(
    test_db_session, monkeypatch
):
    await _seed_dependencies(test_db_session)
    collection_date = "2026-06-02"
    as_of = date(2026, 6, 1)
    slot_detail = {
        "blood_collection": {
            collection_date: {"is_enable": True, "cabins": []},
        }
    }
    await _insert_slot_detail(test_db_session, slot_detail_id=9701, slot_detail=slot_detail)
    await _insert_engagement(
        test_db_session,
        engagement_id=9701,
        engagement_code="ENG9701",
        status="running",
        slot_detail_id=9701,
        recipient_types=("assistants.phlebo", "assistants.staff"),
    )
    await _assign_partner(test_db_session, partner_id=701, engagement_id=9701)
    await _assign_partner(
        test_db_session, partner_id=702, engagement_id=9701, role="expert"
    )
    await _assign_staff(test_db_session, employee_id=801, engagement_id=9701)
    await test_db_session.commit()

    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)

    notifications_service, engagements_repository = _services()
    result = await dispatch_booking_guide_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=False,
    )
    await test_db_session.commit()

    # 1 phlebo + 1 staff; expert excluded. Each gets whatsapp + email.
    assert result["matched"] == 2
    assert result["sent"] == 2
    assert result["skipped"] == 0
    assert result["failed"] == 0
    assert len(deliver_calls) == 4
    recipient_types = {d.get("recipient_type") for d in result["details"]}
    assert recipient_types == {"assistants.phlebo", "assistants.staff"}


@pytest.mark.asyncio
async def test_booking_guide_reminders_falls_back_to_start_date(test_db_session, monkeypatch):
    await _seed_dependencies(test_db_session)
    as_of = date(2026, 6, 1)
    await _insert_engagement(
        test_db_session,
        engagement_id=9702,
        engagement_code="ENG9702",
        status="scheduled",
        start_date="2026-06-02",
        end_date="2026-06-02",
        slot_detail_id=None,
    )
    await _assign_partner(test_db_session, partner_id=703, engagement_id=9702)
    await test_db_session.commit()

    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)

    notifications_service, engagements_repository = _services()
    result = await dispatch_booking_guide_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=False,
    )
    await test_db_session.commit()

    assert result["matched"] == 1
    assert result["sent"] == 1
    assert len(deliver_calls) == 2


@pytest.mark.asyncio
async def test_booking_guide_reminders_excludes_completed_engagements(test_db_session, monkeypatch):
    await _seed_dependencies(test_db_session)
    as_of = date(2026, 6, 1)
    await _insert_engagement(
        test_db_session,
        engagement_id=9703,
        engagement_code="ENG9703",
        status="completed",
        start_date="2026-06-02",
        end_date="2026-06-02",
    )
    await _assign_partner(test_db_session, partner_id=704, engagement_id=9703)
    await test_db_session.commit()

    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)

    notifications_service, engagements_repository = _services()
    result = await dispatch_booking_guide_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=False,
    )
    await test_db_session.commit()

    assert result["matched"] == 0
    assert len(deliver_calls) == 0


@pytest.mark.asyncio
async def test_booking_guide_reminders_skips_wrong_collection_date(test_db_session, monkeypatch):
    await _seed_dependencies(test_db_session)
    as_of = date(2026, 6, 1)
    slot_detail = {
        "blood_collection": {
            "2026-06-05": {"is_enable": True, "cabins": []},
        }
    }
    await _insert_slot_detail(test_db_session, slot_detail_id=9704, slot_detail=slot_detail)
    await _insert_engagement(
        test_db_session,
        engagement_id=9704,
        engagement_code="ENG9704",
        status="running",
        start_date="2026-06-05",
        slot_detail_id=9704,
    )
    await _assign_partner(test_db_session, partner_id=705, engagement_id=9704)
    await test_db_session.commit()

    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)

    notifications_service, engagements_repository = _services()
    result = await dispatch_booking_guide_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=False,
    )
    await test_db_session.commit()

    assert result["matched"] == 0
    assert len(deliver_calls) == 0


@pytest.mark.asyncio
async def test_booking_guide_reminders_dry_run_does_not_dispatch(test_db_session, monkeypatch):
    await _seed_dependencies(test_db_session)
    as_of = date(2026, 6, 1)
    await _insert_engagement(
        test_db_session,
        engagement_id=9705,
        engagement_code="ENG9705",
        status="running",
        start_date="2026-06-02",
    )
    await _assign_partner(test_db_session, partner_id=706, engagement_id=9705)
    await test_db_session.commit()

    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)

    notifications_service, engagements_repository = _services()
    result = await dispatch_booking_guide_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=True,
    )
    await test_db_session.commit()

    assert result["matched"] == 1
    assert result["dry_run"] is True
    assert len(deliver_calls) == 0


@pytest.mark.asyncio
async def test_booking_guide_reminders_dedup_skips_already_sent_per_recipient(
    test_db_session, monkeypatch
):
    await _seed_dependencies(test_db_session)
    as_of = date(2026, 6, 1)
    await _insert_engagement(
        test_db_session,
        engagement_id=9706,
        engagement_code="ENG9706",
        status="running",
        start_date="2026-06-02",
        recipient_types=("assistants.phlebo", "assistants.staff"),
        service_keys=BOOKING_GUIDE_WHATSAPP_KEY,
    )
    await _assign_partner(test_db_session, partner_id=707, engagement_id=9706)
    await _assign_staff(test_db_session, employee_id=807, engagement_id=9706)
    await test_db_session.commit()

    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)

    notifications_service, engagements_repository = _services()
    first = await dispatch_booking_guide_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=False,
    )
    await test_db_session.commit()

    assert first["sent"] == 2
    assert len(deliver_calls) == 2

    # Mark phlebo notification as sent; leave staff as failed so it retries.
    await test_db_session.execute(
        text(
            """
            UPDATE notifications
            SET status = 2
            WHERE engagement_id = 9706
              AND service_key = :sk
              AND ("user"::jsonb -> 'contacts' @> CAST(:partner AS jsonb))
            """
        ),
        {
            "sk": BOOKING_GUIDE_WHATSAPP_KEY,
            "partner": json.dumps([{"partner_id": 707}]),
        },
    )
    await test_db_session.execute(
        text(
            """
            UPDATE notifications
            SET status = 3
            WHERE engagement_id = 9706
              AND service_key = :sk
              AND ("user"::jsonb -> 'contacts' @> CAST(:employee AS jsonb))
            """
        ),
        {
            "sk": BOOKING_GUIDE_WHATSAPP_KEY,
            "employee": json.dumps([{"employee_id": 807}]),
        },
    )
    await test_db_session.commit()

    second = await dispatch_booking_guide_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=False,
    )
    await test_db_session.commit()

    assert second["sent"] == 1
    assert second["skipped"] == 1
    assert len(deliver_calls) == 3  # only staff retried
    skip_details = [d for d in second["details"] if d["action"] == "skipped"]
    assert any(d.get("partner_id") == 707 for d in skip_details)


@pytest.mark.asyncio
async def test_booking_guide_reminders_does_not_notify_expert_only_assignees(
    test_db_session, monkeypatch
):
    await _seed_dependencies(test_db_session)
    as_of = date(2026, 6, 1)
    await _insert_engagement(
        test_db_session,
        engagement_id=9707,
        engagement_code="ENG9707",
        status="running",
        start_date="2026-06-02",
        recipient_types=("assistants.phlebo",),
    )
    await _assign_partner(
        test_db_session, partner_id=708, engagement_id=9707, role="expert"
    )
    await test_db_session.commit()

    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)

    notifications_service, engagements_repository = _services()
    result = await dispatch_booking_guide_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=False,
    )
    await test_db_session.commit()

    assert result["matched"] == 0
    assert len(deliver_calls) == 0


@pytest.mark.asyncio
async def test_booking_guide_reminders_staff_only_binding(test_db_session, monkeypatch):
    await _seed_dependencies(test_db_session)
    as_of = date(2026, 6, 1)
    await _insert_engagement(
        test_db_session,
        engagement_id=9708,
        engagement_code="ENG9708",
        status="running",
        start_date="2026-06-02",
        recipient_types=("assistants.staff",),
        service_keys=BOOKING_GUIDE_WHATSAPP_KEY,
    )
    await _assign_partner(test_db_session, partner_id=709, engagement_id=9708)
    await _assign_staff(test_db_session, employee_id=809, engagement_id=9708)
    await test_db_session.commit()

    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)

    notifications_service, engagements_repository = _services()
    result = await dispatch_booking_guide_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=False,
    )
    await test_db_session.commit()

    assert result["matched"] == 1
    assert result["sent"] == 1
    assert len(deliver_calls) == 1
    assert result["details"][0]["employee_id"] == 809
    assert result["details"][0]["recipient_type"] == "assistants.staff"
