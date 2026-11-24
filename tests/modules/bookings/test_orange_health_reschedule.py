"""Tests for Orange Health home-collection reschedule."""

from __future__ import annotations

from datetime import date, time, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text

from modules.audit.models import IntegrationSyncLog
from modules.diagnostics.models import DiagnosticPackage
from modules.engagements.models import (
    BloodCollectionType,
    Engagement,
    EngagementParticipant,
    ParticipantBloodBooking,
)
from modules.users.models import User


async def _seed_orange_reschedule_fixture(test_db_session):
    engagement_id = 88101
    user_id = 88101
    participant_id = 88101
    diag_id = 88101
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, status) "
            "VALUES (1, 'PKG1', 'Test Package', 1) ON CONFLICT (package_id) DO NOTHING"
        )
    )
    existing_diag = await test_db_session.get(DiagnosticPackage, diag_id)
    if existing_diag is None:
        test_db_session.add(
            DiagnosticPackage(
                diagnostic_package_id=diag_id,
                reference_id="REF88101",
                package_name="Orange Home",
                diagnostic_provider="orange_health",
                external_package_code="PKG_ORANGE",
                status="active",
                bookings_count=0,
            )
        )
    existing_eng = await test_db_session.get(Engagement, engagement_id)
    coll_date = date.today() + timedelta(days=3)
    if existing_eng is None:
        test_db_session.add(
            Engagement(
                engagement_id=engagement_id,
                engagement_name="Orange Reschedule",
                engagement_code="OH88101",
                assessment_package_id=1,
                diagnostic_package_id=diag_id,
                status="running",
                start_date=date.today(),
                end_date=date.today() + timedelta(days=7),
                city="Bangalore",
                blood_collection_type=BloodCollectionType.home_collection,
            )
        )
    existing_user = await test_db_session.get(User, user_id)
    if existing_user is None:
        test_db_session.add(
            User(
                user_id=user_id,
                age=30,
                phone="8810100001",
                email="orange88101@example.com",
                status="active",
                first_name="Or",
                last_name="Ange",
                gender="male",
                relationship="self",
            )
        )
    await test_db_session.flush()
    slot_id = f"{coll_date.isoformat()}T06:00:00"
    existing_participant = await test_db_session.get(EngagementParticipant, participant_id)
    if existing_participant is None:
        test_db_session.add(
            EngagementParticipant(
                engagement_participant_id=participant_id,
                engagement_id=engagement_id,
                user_id=user_id,
                booked_by_user_id=user_id,
                latitude=12.97,
                longitude=77.59,
                address="123 Test St",
            )
        )
    await test_db_session.flush()
    existing_row = (
        await test_db_session.execute(
            select(ParticipantBloodBooking).where(
                ParticipantBloodBooking.engagement_participant_id == participant_id,
                ParticipantBloodBooking.status == "active",
            )
        )
    ).scalar_one_or_none()
    if existing_row is None:
        test_db_session.add(
            ParticipantBloodBooking(
                engagement_participant_id=participant_id,
                collection_date=date.today() + timedelta(days=1),
                collection_time=time(10, 0),
                collection_time_slot_id=slot_id,
                booking_id="BLR88101",
                barcode="OH88101",
                diagnostic_provider="orange_health",
                request_id="BLR88101",
                token="tok-88101",
                status="active",
            )
        )
    else:
        existing_row.collection_time_slot_id = slot_id
        existing_row.request_id = "BLR88101"
        existing_row.token = "tok-88101"
        existing_row.booking_id = "BLR88101"
    await test_db_session.commit()
    return engagement_id, user_id, participant_id, coll_date, slot_id


@pytest.mark.asyncio
async def test_orange_reschedule_success_logs_and_updates_row(test_db_session):
    engagement_id, user_id, participant_id, coll_date, slot_id = await _seed_orange_reschedule_fixture(
        test_db_session
    )

    participant = await test_db_session.get(EngagementParticipant, participant_id)
    engagement = await test_db_session.get(Engagement, engagement_id)

    from modules.bookings import service as booking_service

    mock_reschedule = AsyncMock(return_value={"result": "ok"})
    mock_serviceability = AsyncMock(
        return_value={
            "slots": {
                slot_id: {"slot_datetime": slot_id, "is_morning_slot": True},
            }
        }
    )
    with patch(
        "modules.diagnostics.orange_health.reschedule_helpers.orange_health_client.check_serviceability",
        mock_serviceability,
    ), patch(
        "modules.bookings.service.orange_health_client.reschedule_order",
        mock_reschedule,
    ):
        result = await booking_service.reschedule_orange_participant_booking(
            test_db_session,
            participant=participant,
            engagement=engagement,
            blood_collection_date=coll_date,
            blood_collection_time_slot_id=slot_id,
            blood_collection_time_slot="06:00 AM",
            reschedule_reason="Patient not available",
        )

    assert result["status"] is True
    assert result["booking_id"] == "BLR88101"
    mock_reschedule.assert_awaited_once()
    call_kwargs = mock_reschedule.await_args.kwargs
    assert call_kwargs["request_id"] == "BLR88101"
    assert call_kwargs["token"] == "tok-88101"
    assert call_kwargs["payload"]["requested_slot_time"] == slot_id
    assert call_kwargs["payload"]["reschedule_explanation"] == "Patient not available"

    logs = (
        await test_db_session.execute(
            select(IntegrationSyncLog).where(
                IntegrationSyncLog.engagement_id == engagement_id,
                IntegrationSyncLog.provider == "orange_health",
            )
        )
    ).scalars().all()
    assert any(log.status == "success" for log in logs)
    success_log = next(log for log in logs if log.status == "success")
    req = success_log.request_payload
    assert req.get("body", {}).get("requested_slot_time") == slot_id
    assert "internal" in req
    assert "audit" not in req.get("body", {})

    rows = (
        await test_db_session.execute(
            select(ParticipantBloodBooking).where(
                ParticipantBloodBooking.engagement_participant_id == participant_id
            )
        )
    ).scalars().all()
    assert len(rows) >= 2
    active = [r for r in rows if r.status == "active"]
    assert len(active) == 1
    assert active[0].request_id == "BLR88101"
    assert active[0].token == "tok-88101"
    assert active[0].collection_time_slot_id == slot_id


@pytest.mark.asyncio
async def test_orange_reschedule_failure_persists_isolated_sync_log(test_db_session):
    engagement_id, user_id, participant_id, coll_date, slot_id = await _seed_orange_reschedule_fixture(
        test_db_session
    )

    participant = await test_db_session.get(EngagementParticipant, participant_id)
    engagement = await test_db_session.get(Engagement, engagement_id)

    from modules.bookings import service as booking_service
    from modules.diagnostics.orange_health.client import OrangeHealthApiError

    mock_serviceability = AsyncMock(
        return_value={
            "slots": {
                slot_id: {"slot_datetime": slot_id, "is_morning_slot": True},
            }
        }
    )
    mock_reschedule = AsyncMock(
        side_effect=OrangeHealthApiError("slot gone", status_code=400, body={"status": "slot gone"})
    )
    with patch(
        "modules.diagnostics.orange_health.reschedule_helpers.orange_health_client.check_serviceability",
        mock_serviceability,
    ), patch(
        "modules.bookings.service.orange_health_client.reschedule_order",
        mock_reschedule,
    ):
        with pytest.raises(Exception):
            await booking_service.reschedule_orange_participant_booking(
                test_db_session,
                participant=participant,
                engagement=engagement,
                blood_collection_date=coll_date,
                blood_collection_time_slot_id=slot_id,
                blood_collection_time_slot="06:00 AM",
                reschedule_reason="Patient not available",
            )

    logs = (
        await test_db_session.execute(
            select(IntegrationSyncLog).where(
                IntegrationSyncLog.engagement_id == engagement_id,
                IntegrationSyncLog.provider == "orange_health",
                IntegrationSyncLog.status == "failed",
            )
        )
    ).scalars().all()
    assert len(logs) >= 1
    failed = logs[-1]
    assert failed.request_payload.get("body", {}).get("requested_slot_time") == slot_id
    assert failed.error_message


@pytest.mark.asyncio
async def test_orange_reschedule_skips_patch_when_slot_unavailable(test_db_session):
    engagement_id, user_id, participant_id, coll_date, slot_id = await _seed_orange_reschedule_fixture(
        test_db_session
    )

    participant = await test_db_session.get(EngagementParticipant, participant_id)
    engagement = await test_db_session.get(Engagement, engagement_id)

    from modules.bookings import service as booking_service

    mock_reschedule = AsyncMock(return_value={"result": "ok"})
    mock_serviceability = AsyncMock(return_value={"slots": {}})
    with patch(
        "modules.diagnostics.orange_health.reschedule_helpers.orange_health_client.check_serviceability",
        mock_serviceability,
    ), patch(
        "modules.bookings.service.orange_health_client.reschedule_order",
        mock_reschedule,
    ):
        with pytest.raises(Exception) as exc:
            await booking_service.reschedule_orange_participant_booking(
                test_db_session,
                participant=participant,
                engagement=engagement,
                blood_collection_date=coll_date,
                blood_collection_time_slot_id=slot_id,
                blood_collection_time_slot="06:00 AM",
                reschedule_reason="Patient not available",
            )
    assert getattr(exc.value, "error_code", None) == "SLOT_NOT_AVAILABLE"
    mock_reschedule.assert_not_awaited()