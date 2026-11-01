"""Tests for notification binding resolution."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from modules.notifications.binding_resolver import filters_match, resolve_bindings_for_event


def test_filters_match_discount_code():
    assert filters_match(
        {"discount_code": "SAVE10"},
        {"discount": {"discount_code": "SAVE10"}},
    )
    assert not filters_match({"discount_code": "SAVE10"}, {"discount": {"discount_code": "OTHER"}})


@pytest.mark.asyncio
async def test_resolve_bindings_global_only(test_db_session):
    await test_db_session.execute(
        text(
            "INSERT INTO notification_events "
            "(event_code, event_name, recipient_type, notification_services, is_active) "
            "VALUES ('auth.otp.sent', 'OTP', 'participant', CAST(:svc AS jsonb), true) "
            "ON CONFLICT (event_code, recipient_type) DO UPDATE SET notification_services = EXCLUDED.notification_services"
        ),
        {"svc": json.dumps(["whatapi-otp"])},
    )
    await test_db_session.commit()

    bindings = await resolve_bindings_for_event(
        test_db_session,
        event_code="auth.otp.sent",
        engagement_id=None,
        payload={"service_key": "whatapi-otp", "recipient_type": "participant"},
    )
    assert len(bindings) == 1
    assert bindings[0].recipient_type == "participant"
    assert bindings[0].notification_services[0].service_key == "whatapi-otp"


@pytest.mark.asyncio
async def test_emit_event_no_binding_returns_empty(test_db_session):
    from modules.notifications.engine import emit_event

    ids = await emit_event(
        test_db_session,
        event_code="system.cpu.alert",
        payload={"user_ids": [1]},
        engagement_id=None,
    )
    assert ids == []
