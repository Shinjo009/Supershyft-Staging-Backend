"""Tests for consultation guide reminder dispatch."""

from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import text

from modules.engagements.repository import EngagementsRepository
from modules.notifications.consultation_guide_reminders import (
    dispatch_consultation_guide_reminders,
)
from modules.notifications.repository import NotificationsRepository
from modules.notifications.service import NotificationsService
from tests.helpers.auth import seed_employee, seed_partner
from tests.modules.notifications.dispatch_mocks import patch_service_direct_deliver
from tests.modules.notifications.notification_event_seed import upsert_engagement_notification
from tests.modules.notifications.sql_helpers import engagement_status_code

CONSULTATION_GUIDE_WHATSAPP_KEY = "reminders-consultation-guide-whatsapp-1"
CONSULTATION_GUIDE_EMAIL_KEY = "consultation-guide-email"
DEFAULT_CONSULTATION_GUIDE_KEYS = (
    f"{CONSULTATION_GUIDE_WHATSAPP_KEY},{CONSULTATION_GUIDE_EMAIL_KEY}"
)


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
        (CONSULTATION_GUIDE_WHATSAPP_KEY, "whatsapp", "send-expert-consultation-guide-whatsapp-v1"),
        (CONSULTATION_GUIDE_EMAIL_KEY, "email", "consultation-guide-email"),
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
            "VALUES ('bio_ai_with_consultation', 'BioAI Consult', true) "
            "ON CONFLICT (code) DO UPDATE SET is_active = true"
        )
    )
    await test_db_session.commit()


async def _bind_consultation_guide_services(
    test_db_session,
    *,
    engagement_id: int,
    service_keys: str = DEFAULT_CONSULTATION_GUIDE_KEYS,
    recipient_types: tuple[str, ...] = ("assistants.expert",),
) -> None:
    for recipient_type in recipient_types:
        await upsert_engagement_notification(
            test_db_session,
            engagement_id=engagement_id,
            event_code="reminders.consultation_guide",
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
    service_keys: str = DEFAULT_CONSULTATION_GUIDE_KEYS,
    recipient_types: tuple[str, ...] = ("assistants.expert",),
) -> None:
    slot_value = "NULL" if slot_detail_id is None else str(slot_detail_id)
    await test_db_session.execute(
        text(
            "INSERT INTO engagements "
            "(engagement_id, engagement_name, engagement_code, engagement_type, assessment_package_id, "
            "diagnostic_package_id, city, slot_duration, start_date, end_date, status, organization_id, slot_detail_id) "
            f"VALUES ({engagement_id}, 'Camp {engagement_id}', '{engagement_code}', "
            "(SELECT id FROM engagement_types WHERE code = 'bio_ai_with_consultation'), 1, 1, 'BLR', 20, "
            f"'{start_date}', '{end_date}', {engagement_status_code(status)}, NULL, {slot_value})"
        )
    )
    if bind_services:
        await _bind_consultation_guide_services(
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
    role: str = "expert",
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
async def test_consultation_guide_reminders_dispatch_to_expert_and_staff(
    test_db_session, monkeypatch
):
    await _seed_dependencies(test_db_session)
    consultation_date = "2026-06-02"
    as_of = date(2026, 6, 1)
    slot_detail = {
        "consultation": {
            consultation_date: {"is_enable": True, "cabins": []},
        }
    }
    await _insert_slot_detail(test_db_session, slot_detail_id=9801, slot_detail=slot_detail)
    await _insert_engagement(
        test_db_session,
        engagement_id=9801,
        engagement_code="ENG9801",
        status="running",
        slot_detail_id=9801,
        recipient_types=("assistants.expert", "assistants.staff"),
    )
    await _assign_partner(test_db_session, partner_id=901, engagement_id=9801, role="expert")
    await _assign_partner(
        test_db_session, partner_id=902, engagement_id=9801, role="phlebo"
    )
    await _assign_staff(test_db_session, employee_id=901, engagement_id=9801)
    await test_db_session.commit()

    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)

    notifications_service, engagements_repository = _services()
    result = await dispatch_consultation_guide_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=False,
    )
    await test_db_session.commit()

    assert result["matched"] == 2
    assert result["sent"] == 2
    assert result["skipped"] == 0
    assert result["failed"] == 0
    assert len(deliver_calls) == 4
    recipient_types = {d.get("recipient_type") for d in result["details"]}
    assert recipient_types == {"assistants.expert", "assistants.staff"}


@pytest.mark.asyncio
async def test_consultation_guide_reminders_no_start_date_fallback(
    test_db_session, monkeypatch
):
    await _seed_dependencies(test_db_session)
    as_of = date(2026, 6, 1)
    await _insert_engagement(
        test_db_session,
        engagement_id=9802,
        engagement_code="ENG9802",
        status="scheduled",
        start_date="2026-06-02",
        end_date="2026-06-02",
        slot_detail_id=None,
    )
    await _assign_partner(test_db_session, partner_id=903, engagement_id=9802)
    await test_db_session.commit()

    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)

    notifications_service, engagements_repository = _services()
    result = await dispatch_consultation_guide_reminders(
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
async def test_consultation_guide_reminders_excludes_completed_engagements(
    test_db_session, monkeypatch
):
    await _seed_dependencies(test_db_session)
    consultation_date = "2026-06-02"
    as_of = date(2026, 6, 1)
    slot_detail = {
        "consultation": {
            consultation_date: {"is_enable": True, "cabins": []},
        }
    }
    await _insert_slot_detail(test_db_session, slot_detail_id=9803, slot_detail=slot_detail)
    await _insert_engagement(
        test_db_session,
        engagement_id=9803,
        engagement_code="ENG9803",
        status="completed",
        slot_detail_id=9803,
    )
    await _assign_partner(test_db_session, partner_id=904, engagement_id=9803)
    await test_db_session.commit()

    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)

    notifications_service, engagements_repository = _services()
    result = await dispatch_consultation_guide_reminders(
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
async def test_consultation_guide_reminders_skips_wrong_consultation_date(
    test_db_session, monkeypatch
):
    await _seed_dependencies(test_db_session)
    as_of = date(2026, 6, 1)
    slot_detail = {
        "consultation": {
            "2026-06-05": {"is_enable": True, "cabins": []},
        }
    }
    await _insert_slot_detail(test_db_session, slot_detail_id=9804, slot_detail=slot_detail)
    await _insert_engagement(
        test_db_session,
        engagement_id=9804,
        engagement_code="ENG9804",
        status="running",
        slot_detail_id=9804,
    )
    await _assign_partner(test_db_session, partner_id=905, engagement_id=9804)
    await test_db_session.commit()

    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)

    notifications_service, engagements_repository = _services()
    result = await dispatch_consultation_guide_reminders(
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
async def test_consultation_guide_reminders_skips_disabled_consultation_date(
    test_db_session, monkeypatch
):
    await _seed_dependencies(test_db_session)
    as_of = date(2026, 6, 1)
    slot_detail = {
        "consultation": {
            "2026-06-02": {"is_enable": False, "cabins": []},
        }
    }
    await _insert_slot_detail(test_db_session, slot_detail_id=9805, slot_detail=slot_detail)
    await _insert_engagement(
        test_db_session,
        engagement_id=9805,
        engagement_code="ENG9805",
        status="running",
        slot_detail_id=9805,
    )
    await _assign_partner(test_db_session, partner_id=906, engagement_id=9805)
    await test_db_session.commit()

    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)

    notifications_service, engagements_repository = _services()
    result = await dispatch_consultation_guide_reminders(
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
async def test_consultation_guide_reminders_dry_run_does_not_dispatch(
    test_db_session, monkeypatch
):
    await _seed_dependencies(test_db_session)
    consultation_date = "2026-06-02"
    as_of = date(2026, 6, 1)
    slot_detail = {
        "consultation": {
            consultation_date: {"is_enable": True, "cabins": []},
        }
    }
    await _insert_slot_detail(test_db_session, slot_detail_id=9806, slot_detail=slot_detail)
    await _insert_engagement(
        test_db_session,
        engagement_id=9806,
        engagement_code="ENG9806",
        status="running",
        slot_detail_id=9806,
    )
    await _assign_partner(test_db_session, partner_id=907, engagement_id=9806)
    await test_db_session.commit()

    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)

    notifications_service, engagements_repository = _services()
    result = await dispatch_consultation_guide_reminders(
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
async def test_consultation_guide_reminders_dedup_skips_already_sent_per_recipient(
    test_db_session, monkeypatch
):
    await _seed_dependencies(test_db_session)
    consultation_date = "2026-06-02"
    as_of = date(2026, 6, 1)
    slot_detail = {
        "consultation": {
            consultation_date: {"is_enable": True, "cabins": []},
        }
    }
    await _insert_slot_detail(test_db_session, slot_detail_id=9807, slot_detail=slot_detail)
    await _insert_engagement(
        test_db_session,
        engagement_id=9807,
        engagement_code="ENG9807",
        status="running",
        slot_detail_id=9807,
        recipient_types=("assistants.expert", "assistants.staff"),
        service_keys=CONSULTATION_GUIDE_WHATSAPP_KEY,
    )
    await _assign_partner(test_db_session, partner_id=908, engagement_id=9807)
    await _assign_staff(test_db_session, employee_id=908, engagement_id=9807)
    await test_db_session.commit()

    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)

    notifications_service, engagements_repository = _services()
    first = await dispatch_consultation_guide_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=False,
    )
    await test_db_session.commit()

    assert first["sent"] == 2
    assert len(deliver_calls) == 2

    await test_db_session.execute(
        text(
            """
            UPDATE notifications
            SET status = 2
            WHERE engagement_id = 9807
              AND service_key = :sk
              AND ("user"::jsonb -> 'contacts' @> CAST(:partner AS jsonb))
            """
        ),
        {
            "sk": CONSULTATION_GUIDE_WHATSAPP_KEY,
            "partner": json.dumps([{"partner_id": 908}]),
        },
    )
    await test_db_session.execute(
        text(
            """
            UPDATE notifications
            SET status = 3
            WHERE engagement_id = 9807
              AND service_key = :sk
              AND ("user"::jsonb -> 'contacts' @> CAST(:employee AS jsonb))
            """
        ),
        {
            "sk": CONSULTATION_GUIDE_WHATSAPP_KEY,
            "employee": json.dumps([{"employee_id": 908}]),
        },
    )
    await test_db_session.commit()

    second = await dispatch_consultation_guide_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=False,
    )
    await test_db_session.commit()

    assert second["sent"] == 1
    assert second["skipped"] == 1
    assert len(deliver_calls) == 3
    skip_details = [d for d in second["details"] if d["action"] == "skipped"]
    assert any(d.get("partner_id") == 908 for d in skip_details)


@pytest.mark.asyncio
async def test_consultation_guide_reminders_does_not_notify_phlebo_only_assignees(
    test_db_session, monkeypatch
):
    await _seed_dependencies(test_db_session)
    consultation_date = "2026-06-02"
    as_of = date(2026, 6, 1)
    slot_detail = {
        "consultation": {
            consultation_date: {"is_enable": True, "cabins": []},
        }
    }
    await _insert_slot_detail(test_db_session, slot_detail_id=9808, slot_detail=slot_detail)
    await _insert_engagement(
        test_db_session,
        engagement_id=9808,
        engagement_code="ENG9808",
        status="running",
        slot_detail_id=9808,
        recipient_types=("assistants.expert",),
    )
    await _assign_partner(
        test_db_session, partner_id=909, engagement_id=9808, role="phlebo"
    )
    await test_db_session.commit()

    deliver_calls: list[dict] = []
    patch_service_direct_deliver(monkeypatch, deliver_calls)

    notifications_service, engagements_repository = _services()
    result = await dispatch_consultation_guide_reminders(
        test_db_session,
        notifications_service=notifications_service,
        engagements_repository=engagements_repository,
        as_of=as_of,
        dry_run=False,
    )
    await test_db_session.commit()

    assert result["matched"] == 0
    assert len(deliver_calls) == 0