"""Tests for console cancel booking (`DELETE .../console/participants/{user_id}/book`)."""

from __future__ import annotations

from datetime import date, time, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from modules.assessments.models import AssessmentPackage
from modules.diagnostics.models import DiagnosticPackage
from modules.engagements.models import (
    BloodCollectionType,
    Engagement,
    EngagementParticipant,
    ParticipantBloodBooking,
)
from modules.users.models import User
from tests.helpers.auth import employee_auth_header, seed_employee
from tests.helpers.console_camp import get_current_blood_booking, upsert_camp_participant_with_schedule


def _auth_header(employee_id: int) -> dict[str, str]:
    return employee_auth_header(employee_id)


@pytest.mark.asyncio
async def test_console_cancel_booking_success(async_client, test_db_session):
    existing_pkg = await test_db_session.get(AssessmentPackage, 1)
    if existing_pkg is None:
        test_db_session.add(
            AssessmentPackage(
                package_id=1,
                package_code="PKG001",
                display_name="Test Package",
                status="active",
            )
        )
    existing_diag = await test_db_session.get(DiagnosticPackage, 50)
    if existing_diag is None:
        test_db_session.add(
            DiagnosticPackage(
                diagnostic_package_id=50,
                reference_id="REF50",
                package_name="Healthians Camp",
                diagnostic_provider="healthians",
                external_package_code="1001",
                status="active",
                bookings_count=0,
            )
        )
    else:
        existing_diag.diagnostic_provider = "healthians"
        existing_diag.external_package_code = "1001"
    await seed_employee(test_db_session, employee_id=501, role="admin", commit=False)

    existing_eng = await test_db_session.get(Engagement, 7001)
    if existing_eng is None:
        test_db_session.add(
            Engagement(
                engagement_id=7001,
                engagement_name="Camp Eng",
                engagement_code="CAMP7001",
                engagement_type=None,
                assessment_package_id=1,
                diagnostic_package_id=50,
                external_camp_id=1001,
                status="running",
                start_date=date.today(),
                end_date=date.today(),
                latitude=28.6,
                longitude=77.2,
                pincode="110001",
                address="Camp Address",
            )
        )
    else:
        existing_eng.diagnostic_package_id = 50
        existing_eng.external_camp_id = 1001
        existing_eng.status = "running"
        existing_eng.latitude = 28.6
        existing_eng.longitude = 77.2
        existing_eng.pincode = "110001"
        existing_eng.address = "Camp Address"
    test_db_session.add(
        User(
            user_id=93002,
            age=35,
            phone="9300200000",
            status="active",
            first_name="Pat",
            last_name="Participant",
            gender="male",
            relationship="self",
        )
    )
    await test_db_session.flush()
    await upsert_camp_participant_with_schedule(
        test_db_session,
        engagement_participant_id=95001,
        engagement_id=7001,
        user_id=93002,
        collection_date=date.today(),
        collection_time=time(10, 0),
        booking_id="1715622590",
        barcode="BC95001",
    )
    await test_db_session.commit()

    mock_cancel = AsyncMock(
        return_value={"status": True, "message": "Order Cancelled Successfully!", "data": None, "code": 200}
    )

    with patch("modules.bookings.service.healthians_client.cancel_booking", mock_cancel):
        with patch("modules.bookings.service.healthians_client.get_access_token", AsyncMock(return_value="token")):
            response = await async_client.delete(
                "/engagements/7001/console/participants/93002/book",
                params={"remarks": "Testing cancel"},
                headers=_auth_header(501),
            )

    assert response.status_code == 200
    assert response.json()["data"]["status"] is True
    mock_cancel.assert_awaited_once()
    call_kwargs = mock_cancel.await_args.kwargs
    assert call_kwargs["booking_id"] == "1715622590"
    assert call_kwargs["vendor_billing_user_id"] == "93002"
    assert call_kwargs["vendor_customer_id"] == "93002"
    assert call_kwargs["remarks"] == "Testing cancel"

    blood_row = await get_current_blood_booking(
        test_db_session, engagement_participant_id=95001
    )
    assert blood_row is not None
    assert blood_row.booking_id is None
    assert blood_row.barcode is None


@pytest.mark.asyncio
async def test_console_cancel_booking_requires_remarks(async_client, test_db_session):
    existing_pkg = await test_db_session.get(AssessmentPackage, 1)
    if existing_pkg is None:
        test_db_session.add(
            AssessmentPackage(
                package_id=1,
                package_code="PKG001",
                display_name="Test Package",
                status="active",
            )
        )
    await seed_employee(test_db_session, employee_id=511, role="admin", commit=False)
    test_db_session.add(
        Engagement(
            engagement_id=7002,
            engagement_name="Camp Eng 2",
            engagement_code="CAMP7002",
            engagement_type=None,
            assessment_package_id=1,
            diagnostic_package_id=1,
            status="running",
            start_date=date.today(),
            end_date=date.today(),
        )
    )
    await test_db_session.commit()

    response = await async_client.delete(
        "/engagements/7002/console/participants/1/book",
        params={"remarks": "  "},
        headers=_auth_header(511),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_console_cancel_booking_orange_health(async_client, test_db_session):
    engagement_id = 7003
    user_id = 93003
    participant_id = 95003
    diag_id = 7003

    existing_pkg = await test_db_session.get(AssessmentPackage, 1)
    if existing_pkg is None:
        test_db_session.add(
            AssessmentPackage(
                package_id=1,
                package_code="PKG001",
                display_name="Test Package",
                status="active",
            )
        )
    existing_diag = await test_db_session.get(DiagnosticPackage, diag_id)
    if existing_diag is None:
        test_db_session.add(
            DiagnosticPackage(
                diagnostic_package_id=diag_id,
                reference_id="REF7003",
                package_name="Orange Home Console",
                diagnostic_provider="orange_health",
                external_package_code="OH7003",
                status="active",
                bookings_count=0,
            )
        )
    else:
        existing_diag.diagnostic_provider = "orange_health"

    await seed_employee(test_db_session, employee_id=503, role="admin", commit=False)

    existing_eng = await test_db_session.get(Engagement, engagement_id)
    if existing_eng is None:
        test_db_session.add(
            Engagement(
                engagement_id=engagement_id,
                engagement_name="Orange Home Eng",
                engagement_code="OH7003",
                assessment_package_id=1,
                diagnostic_package_id=diag_id,
                status="running",
                start_date=date.today(),
                end_date=date.today() + timedelta(days=7),
                blood_collection_type=BloodCollectionType.home_collection,
                city="Bangalore",
            )
        )
    else:
        existing_eng.diagnostic_package_id = diag_id
        existing_eng.blood_collection_type = BloodCollectionType.home_collection
        existing_eng.status = "running"

    test_db_session.add(
        User(
            user_id=user_id,
            age=28,
            phone="9300300000",
            status="active",
            first_name="Orange",
            last_name="Patient",
            gender="male",
            relationship="self",
        )
    )
    await test_db_session.flush()
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
    test_db_session.add(
        ParticipantBloodBooking(
            engagement_participant_id=participant_id,
            collection_date=date.today() + timedelta(days=2),
            collection_time=time(7, 0),
            collection_time_slot_id="2026-12-01T07:00:00",
            booking_id="BLR7003",
            barcode="OH7003",
            diagnostic_provider="orange_health",
            request_id="BLR7003",
            token="tok-7003",
            status="active",
        )
    )
    await test_db_session.commit()

    mock_cancel = AsyncMock(
        return_value={
            "status": {
                "status": "Cancellation Request with ID : BLR7003 is in process",
            }
        }
    )

    with patch("modules.bookings.service.orange_health_client.cancel_order", mock_cancel):
        response = await async_client.delete(
            f"/engagements/{engagement_id}/console/participants/{user_id}/book",
            params={
                "remarks": "Customer requested cancel",
                "cancellation_explanation": "Patient unavailable on scheduled day",
            },
            headers=_auth_header(503),
        )

    assert response.status_code == 200
    assert response.json()["data"]["status"] is True
    mock_cancel.assert_awaited_once()
    call_kwargs = mock_cancel.await_args.kwargs
    assert call_kwargs["request_id"] == "BLR7003"
    assert call_kwargs["token"] == "tok-7003"
    assert call_kwargs["payload"]["cancellationReason"] == "Customer requested cancel"
    assert call_kwargs["payload"]["cancellationExplanation"] == "Patient unavailable on scheduled day"

    blood_row = (
        await test_db_session.execute(
            select(ParticipantBloodBooking).where(
                ParticipantBloodBooking.engagement_participant_id == participant_id,
                ParticipantBloodBooking.status == "cancelled",
            )
        )
    ).scalar_one_or_none()
    assert blood_row is not None
    assert blood_row.booking_id is None
    assert blood_row.request_id is None
    assert blood_row.token is None


@pytest.mark.asyncio
async def test_console_cancel_booking_orange_requires_explanation(async_client, test_db_session):
    engagement_id = 7004
    user_id = 93004
    participant_id = 95004
    diag_id = 7004

    existing_pkg = await test_db_session.get(AssessmentPackage, 1)
    if existing_pkg is None:
        test_db_session.add(
            AssessmentPackage(
                package_id=1,
                package_code="PKG001",
                display_name="Test Package",
                status="active",
            )
        )
    test_db_session.add(
        DiagnosticPackage(
            diagnostic_package_id=diag_id,
            reference_id="REF7004",
            package_name="Orange Home Console",
            diagnostic_provider="orange_health",
            external_package_code="OH7004",
            status="active",
            bookings_count=0,
        )
    )
    await seed_employee(test_db_session, employee_id=504, role="admin", commit=False)
    test_db_session.add(
        Engagement(
            engagement_id=engagement_id,
            engagement_name="Orange Home Eng",
            engagement_code="OH7004",
            assessment_package_id=1,
            diagnostic_package_id=diag_id,
            status="running",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=7),
            blood_collection_type=BloodCollectionType.home_collection,
            city="Bangalore",
        )
    )
    test_db_session.add(
        User(
            user_id=user_id,
            age=28,
            phone="9300400000",
            status="active",
            first_name="Orange",
            last_name="Patient",
            gender="male",
            relationship="self",
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        EngagementParticipant(
            engagement_participant_id=participant_id,
            engagement_id=engagement_id,
            user_id=user_id,
            booked_by_user_id=user_id,
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        ParticipantBloodBooking(
            engagement_participant_id=participant_id,
            collection_date=date.today() + timedelta(days=2),
            collection_time=time(7, 0),
            booking_id="BLR7004",
            diagnostic_provider="orange_health",
            request_id="BLR7004",
            token="tok-7004",
            status="active",
        )
    )
    await test_db_session.commit()

    response = await async_client.delete(
        f"/engagements/{engagement_id}/console/participants/{user_id}/book",
        params={"remarks": "Only reason provided"},
        headers=_auth_header(504),
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_CANCELLATION_EXPLANATION"
