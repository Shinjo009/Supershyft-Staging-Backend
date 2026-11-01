"""Unit tests for onboarding enrollment notifications."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from modules.engagements.constants import DEFAULT_ENGAGEMENT_NOTIFICATION_SERVICE_KEY
from modules.engagements.repository import EngagementsRepository
from modules.notifications.onboarding_notify import (
    detail_or_hyphen,
    notify_onboarding_assistants_on_enrollment,
    participant_details_from_user,
)
from modules.notifications.repository import NotificationsRepository
from modules.notifications.schemas import DispatchRequest
from modules.notifications.service import NotificationsService
from modules.users.schemas import PublicUserOnboardRequest
from modules.users.service import UsersService
from tests.modules.notifications.notification_test_seeds import upsert_notification_service


async def _seed_notification_service(
    test_db_session,
    *,
    service_key: str,
    require_participant_detail: bool = False,
    is_active: bool = True,
) -> None:
    _ = require_participant_detail
    await upsert_notification_service(
        test_db_session,
        service_key=service_key,
        channel="whatsapp",
        hint="participant_detail" if require_participant_detail else None,
        is_active=is_active,
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def _seed_diagnostic_package(test_db_session, diagnostic_package_id: int = 1) -> None:
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, reference_id, package_name, diagnostic_provider, status, bookings_count) "
            "VALUES (:did, 'REF1', 'Diag', 'healthians', 1, 0) ON CONFLICT (diagnostic_package_id) DO NOTHING"
        ),
        {"did": diagnostic_package_id},
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_notify_uses_engagement_service_key(test_db_session, monkeypatch):
    from types import SimpleNamespace

    default_key = DEFAULT_ENGAGEMENT_NOTIFICATION_SERVICE_KEY
    await _seed_notification_service(test_db_session, service_key=default_key)
    await _seed_diagnostic_package(test_db_session)

    engagement = SimpleNamespace(engagement_id=99001)

    emit_mock = AsyncMock(return_value=[1])
    monkeypatch.setattr(
        "modules.notifications.engine.emit_event",
        emit_mock,
    )

    engagements_repo = EngagementsRepository()
    monkeypatch.setattr(
        engagements_repo,
        "list_onboarding_assistant_notify_contacts",
        AsyncMock(return_value=[{"phone": "9999999999", "first_name": "OA"}]),
    )

    notifications_service = NotificationsService(NotificationsRepository())
    await notify_onboarding_assistants_on_enrollment(
        test_db_session,
        notifications_service=notifications_service,
        notifications_repository=NotificationsRepository(),
        engagements_repository=engagements_repo,
        engagement=engagement,
        participant_user_id=5001,
        participant_details={
            "name": "Test User",
            "email": "t@example.com",
            "participant_user_id": "5001",
        },
    )

    emit_mock.assert_awaited_once()
    kwargs = emit_mock.await_args.kwargs
    assert kwargs["event_code"] == "onboarding.completed"
    assert kwargs["engagement_id"] == 99001
    assert kwargs["payload"]["participant_user_id"] == 5001
    assert kwargs["payload"]["participant_details"]["participant_user_id"] == "5001"
    assert "recipient_type" not in kwargs["payload"]
    assert kwargs["payload"]["user_id"] == 5001


@pytest.mark.asyncio
async def test_notify_skips_when_participant_details_required_but_missing(test_db_session, monkeypatch):
    from types import SimpleNamespace

    service_key = "needs-participant-detail"
    await _seed_notification_service(
        test_db_session, service_key=service_key, require_participant_detail=True
    )
    await _seed_diagnostic_package(test_db_session)

    engagement = SimpleNamespace(engagement_id=99002)

    emit_mock = AsyncMock(return_value=[1])
    monkeypatch.setattr(
        "modules.notifications.engine.emit_event",
        emit_mock,
    )

    engagements_repo = EngagementsRepository()
    monkeypatch.setattr(
        engagements_repo,
        "list_onboarding_assistant_notify_contacts",
        AsyncMock(return_value=[{"phone": "9999999999", "first_name": "OA"}]),
    )

    notifications_service = NotificationsService(NotificationsRepository())
    await notify_onboarding_assistants_on_enrollment(
        test_db_session,
        notifications_service=notifications_service,
        notifications_repository=NotificationsRepository(),
        engagements_repository=engagements_repo,
        engagement=engagement,
        participant_user_id=5002,
        participant_details=None,
    )

    emit_mock.assert_awaited_once()
    assert emit_mock.await_args.kwargs["payload"]["participant_details"] is None


def test_detail_or_hyphen_uses_placeholder_for_blank_values():
    assert detail_or_hyphen(None) == "-"
    assert detail_or_hyphen("") == "-"
    assert detail_or_hyphen("   ") == "-"
    assert detail_or_hyphen("BLR") == "BLR"
    assert detail_or_hyphen(30) == "30"


def test_participant_details_from_onboard_payload_fills_missing_with_hyphen():
    payload = PublicUserOnboardRequest(
        first_name="Pratheek",
        last_name="Bedre",
        phone="8762830757",
        email="pratheek.fitnastic@gmail.com",
        age=30,
        gender="male",
        blood_collection_date=date(2026, 8, 23),
        blood_collection_time_slot="09:00",
    )
    details = UsersService._participant_details_from_onboard_payload(
        payload,
        source="public",
        participant_user_id=5,
    )
    assert details["address"] == "-"
    assert details["pincode"] == "-"
    assert details["name"] == "Pratheek Bedre"
    assert details["collection_date"] == "2026-08-23"
    assert details["collection_time"] == "09:00"
    # Must pass DispatchRequest nested-string validation (empty strings previously failed).
    DispatchRequest(
        service_key="booking-alert-whatsapp",
        user_ids=[8],
        engagement_id=1037,
        participant_details=details,
    )


def test_participant_details_from_user_fills_missing_with_hyphen():
    class _User:
        first_name = "Pratheek"
        last_name = "Bedre"
        email = "pratheek.fitnastic@gmail.com"
        phone = "8762830757"
        age = 30
        gender = "male"
        address = None
        pin_code = None
        pincode = None

    details = participant_details_from_user(
        _User(),
        source="public",
        participant_user_id=5,
        collection_date="",
        collection_time=None,
    )
    assert details["address"] == "-"
    assert details["pincode"] == "-"
    assert details["collection_date"] == "-"
    assert details["collection_time"] == "-"
    assert details["cabin_name"] == "-"
    DispatchRequest(
        service_key="booking-alert-whatsapp",
        user_ids=[8],
        engagement_id=1037,
        participant_details=details,
    )
