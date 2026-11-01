"""Regression tests for onboarding.completed binding resolution."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from modules.notifications.binding_resolver import resolve_bindings_for_event


async def _seed_onboarding_bindings(test_db_session) -> None:
    await test_db_session.execute(
        text(
            """
            INSERT INTO notification_events
                (event_code, event_name, recipient_type, notification_services, is_active)
            VALUES
                ('onboarding.completed', 'Onboarding', 'oa.all', CAST(:oa AS jsonb), true),
                ('onboarding.completed', 'Onboarding', 'participant', CAST(:part AS jsonb), true)
            ON CONFLICT (event_code, recipient_type) DO UPDATE SET
                notification_services = EXCLUDED.notification_services,
                is_active = true
            """
        ),
        {
            "oa": json.dumps(["booking-alert-whatsapp"]),
            "part": json.dumps(["welcome-whatsapp", "welcome-email"]),
        },
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_partner_recipient_type_filters_out_oa_and_participant(test_db_session):
    await _seed_onboarding_bindings(test_db_session)

    bindings = await resolve_bindings_for_event(
        test_db_session,
        event_code="onboarding.completed",
        engagement_id=1079,
        payload={
            "recipient_type": "partner",
            "participant_user_id": 14446,
        },
    )
    assert bindings == []


@pytest.mark.asyncio
async def test_onboarding_completed_without_recipient_type_returns_both_bindings(
    test_db_session,
):
    await _seed_onboarding_bindings(test_db_session)

    bindings = await resolve_bindings_for_event(
        test_db_session,
        event_code="onboarding.completed",
        engagement_id=1079,
        payload={"participant_user_id": 14446, "user_id": 14446},
    )
    types = {b.recipient_type for b in bindings}
    assert types == {"oa.all", "participant"}


@pytest.mark.asyncio
async def test_notify_onboarding_emits_without_partner_recipient_type(
    test_db_session, monkeypatch
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from modules.engagements.repository import EngagementsRepository
    from modules.notifications.onboarding_notify import notify_onboarding_assistants_on_enrollment
    from modules.notifications.repository import NotificationsRepository
    from modules.notifications.service import NotificationsService

    engagement = SimpleNamespace(engagement_id=99003)

    emit_mock = AsyncMock(return_value=[1, 2])
    monkeypatch.setattr(
        "modules.notifications.engine.emit_event",
        emit_mock,
    )

    engagements_repo = EngagementsRepository()
    monkeypatch.setattr(
        engagements_repo,
        "list_onboarding_assistant_notify_contacts",
        AsyncMock(return_value=[]),
    )

    notifications_service = NotificationsService(NotificationsRepository())
    await notify_onboarding_assistants_on_enrollment(
        test_db_session,
        notifications_service=notifications_service,
        notifications_repository=NotificationsRepository(),
        engagements_repository=engagements_repo,
        engagement=engagement,
        participant_user_id=5003,
        participant_details={"name": "User", "participant_user_id": "5003"},
    )

    emit_mock.assert_awaited_once()
    payload = emit_mock.await_args.kwargs["payload"]
    assert "recipient_type" not in payload
    assert payload["user_id"] == 5003
    assert payload["participant_user_id"] == 5003
