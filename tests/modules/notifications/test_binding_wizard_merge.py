"""Wizard creates one binding row per delivery channel."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from modules.notifications.binding_schemas import WizardBindingPayload, WizardServiceSpec
from modules.notifications.binding_wizard_service import NotificationBindingWizardService
from modules.notifications.models import NotificationEventBinding, NotificationService


@pytest.mark.asyncio
async def test_create_binding_wizard_separate_channel_rows(test_db_session):
    suffix = uuid.uuid4().hex[:8]
    wa = NotificationService(
        service_key=f"test-wa-{suffix}",
        display_name="Test WA",
        channel="whatsapp",
        webhook_path=f"test-wa-{suffix}",
        is_active=True,
        template_name="test_tpl",
    )
    em = NotificationService(
        service_key=f"test-em-{suffix}",
        display_name="Test Email",
        channel="email",
        webhook_path=f"test-em-{suffix}",
        is_active=True,
        email_subject="Code",
        email_body="Your code",
    )
    test_db_session.add_all([wa, em])
    await test_db_session.flush()

    svc = NotificationBindingWizardService()
    base = {
        "event_code": "users.registered",
        "recipient_type": "user",
        "engagement_type_id": None,
    }
    first = await svc.create_binding_wizard(
        test_db_session,
        WizardBindingPayload(
            **base,
            service=WizardServiceSpec(
                notification_service_id=wa.notification_service_id,
                channel="whatsapp",
            ),
        ),
    )
    second = await svc.create_binding_wizard(
        test_db_session,
        WizardBindingPayload(
            **base,
            service=WizardServiceSpec(
                notification_service_id=em.notification_service_id,
                channel="email",
            ),
        ),
    )
    await test_db_session.commit()

    assert first.id != second.id
    assert first.delivery_channel == "whatsapp"
    assert second.delivery_channel == "email"

    rows = (
        await test_db_session.execute(
            select(NotificationEventBinding).where(
                NotificationEventBinding.event_code == "users.registered",
                NotificationEventBinding.recipient_type == "user",
            )
        )
    ).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_create_binding_wizard_merges_same_slot_services(test_db_session):
    suffix = uuid.uuid4().hex[:8]
    wa1 = NotificationService(
        service_key=f"test-wa-a-{suffix}",
        display_name="Test WA A",
        channel="whatsapp",
        webhook_path=f"test-wa-a-{suffix}",
        is_active=True,
        template_name="test_tpl",
    )
    wa2 = NotificationService(
        service_key=f"test-wa-b-{suffix}",
        display_name="Test WA B",
        channel="whatsapp",
        webhook_path=f"test-wa-b-{suffix}",
        is_active=True,
        template_name="test_tpl",
    )
    test_db_session.add_all([wa1, wa2])
    await test_db_session.flush()

    svc = NotificationBindingWizardService()
    payload_base = {
        "event_code": "payments.completed",
        "recipient_type": "payload",
        "engagement_type_id": None,
        "recipient_config": {"payload_path": "booker.phone", "value_type": "phone"},
        "emit_condition": {"path": "payment.discount_code", "op": "equals", "value": "SUPER99"},
    }
    first = await svc.create_binding_wizard(
        test_db_session,
        WizardBindingPayload(
            **payload_base,
            service=WizardServiceSpec(
                notification_service_id=wa1.notification_service_id,
                channel="whatsapp",
            ),
        ),
    )
    second = await svc.create_binding_wizard(
        test_db_session,
        WizardBindingPayload(
            **payload_base,
            service=WizardServiceSpec(
                notification_service_id=wa2.notification_service_id,
                channel="whatsapp",
            ),
        ),
    )
    await test_db_session.commit()

    assert first.id == second.id
    keys = {s.service_key for s in second.notification_services}
    assert keys == {wa1.service_key, wa2.service_key}

    rows = (
        await test_db_session.execute(
            select(NotificationEventBinding).where(
                NotificationEventBinding.event_code == "payments.completed",
                NotificationEventBinding.recipient_type == "payload",
            )
        )
    ).scalars().all()
    assert len(rows) == 1
