"""Tests for emit_event creating notification rows."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from modules.notifications.engine import emit_event
from modules.notifications.service import NotificationsService


@pytest.mark.asyncio
async def test_emit_event_creates_notification_with_audit_fields(test_db_session, monkeypatch):
    await test_db_session.execute(
        text(
            "INSERT INTO notification_services "
            "(service_key, display_name, channel, webhook_path, is_active, template_name, template_variables) "
            "VALUES ('whatapi-otp', 'OTP WA', 'whatsapp', 'whatapi-otp', true, 'otp_new', CAST(:tv AS jsonb)) "
            "ON CONFLICT (service_key) DO UPDATE SET template_name = EXCLUDED.template_name"
        ),
        {"tv": json.dumps([{"component": "body", "parameters": [{"type": "text", "source": "{{otp.otp}}"}]}])},
    )
    await test_db_session.execute(
        text(
            "INSERT INTO notification_events "
            "(event_code, event_name, recipient_type, notification_services, is_active) "
            "VALUES ('auth.otp.sent', 'OTP', 'participant', CAST(:svc AS jsonb), true) "
            "ON CONFLICT (event_code, recipient_type) DO NOTHING"
        ),
        {"svc": json.dumps(["whatapi-otp"])},
    )
    test_db_session.add(__import__("modules.users.models", fromlist=["User"]).User(user_id=88001, age=30, phone="8800100000", status="active"))
    await test_db_session.commit()

    async def _fake_direct(*args, **kwargs):
        from modules.notifications.direct_dispatch import DirectDispatchOutcome

        return DirectDispatchOutcome(status="queued", message="ok", queue_id="q-test")

    monkeypatch.setattr(
        "modules.notifications.direct_dispatch.try_direct_delivery",
        _fake_direct,
    )

    svc = NotificationsService(repository=__import__("modules.notifications.repository", fromlist=["NotificationsRepository"]).NotificationsRepository())
    ids = await emit_event(
        test_db_session,
        event_code="auth.otp.sent",
        payload={
            "user_id": 88001,
            "otp": "654321",
            "service_key": "whatapi-otp",
            "recipient_type": "participant",
        },
        notifications_service=svc,
        honor_dedup=False,
    )
    assert len(ids) == 1
    row = (
        await test_db_session.execute(
            text(
                "SELECT event_code, recipient_type, service_key FROM notifications "
                "WHERE notification_id = :nid"
            ),
            {"nid": ids[0]},
        )
    ).mappings().one()
    assert row["event_code"] == "auth.otp.sent"
    assert row["recipient_type"] == "participant"
    assert row["service_key"] == "whatapi-otp"
