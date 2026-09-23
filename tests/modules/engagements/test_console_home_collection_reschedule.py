"""Tests for console home-collection reschedule."""

from __future__ import annotations

from datetime import date, time, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from modules.assessments.models import AssessmentPackage
from modules.diagnostics.models import DiagnosticPackage
from modules.engagements.models import BloodCollectionType, Engagement, EngagementParticipant
from modules.users.models import User
from tests.helpers.auth import employee_auth_header, seed_employee


def _auth_header(employee_id: int) -> dict[str, str]:
    return employee_auth_header(employee_id)


async def _seed_home_reschedule_fixture(test_db_session):
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
    existing_diag = await test_db_session.get(DiagnosticPackage, 62)
    if existing_diag is None:
        test_db_session.add(
            DiagnosticPackage(
                diagnostic_package_id=62,
                reference_id="REF62",
                package_name="Healthians Home",
                diagnostic_provider="healthians",
                external_package_id=2004,
                original_price=999,
                status="active",
                bookings_count=0,
            )
        )
    await seed_employee(test_db_session, employee_id=631, role="admin", commit=False)

    existing_eng = await test_db_session.get(Engagement, 7201)
    if existing_eng is None:
        test_db_session.add(
            Engagement(
                engagement_id=7201,
                engagement_name="Home Reschedule Eng",
                engagement_code="HOME7201",
                engagement_type=None,
                assessment_package_id=1,
                diagnostic_package_id=62,
                status="running",
                start_date=date.today(),
                end_date=date.today() + timedelta(days=7),
                city="Bangalore",
                blood_collection_type=BloodCollectionType.home_collection,
            )
        )
    else:
        existing_eng.blood_collection_type = BloodCollectionType.home_collection
        existing_eng.status = "running"
        existing_eng.diagnostic_package_id = 62

    test_db_session.add(
        User(
            user_id=94101,
            age=30,
            phone="9410100000",
            email="reschedule@example.com",
            status="active",
            first_name="Re",
            last_name="Schedule",
            gender="male",
            relationship="self",
        )
    )
    await test_db_session.flush()

    slot_date = (date.today() + timedelta(days=2)).isoformat()
    existing_participant = await test_db_session.get(EngagementParticipant, 97001)
    if existing_participant is None:
        test_db_session.add(
            EngagementParticipant(
                engagement_participant_id=97001,
                engagement_id=7201,
                user_id=94101,
                booked_by_user_id=94101,
                engagement_date=date.today() + timedelta(days=2),
                slot_start_time=time(10, 0),
                booking_id="1387699587154",
                barcode="1387699587154",
                blood_collection_time_slot_id="STM_OLD",
                latitude=12.97,
                longitude=77.59,
                pincode="560001",
                city="Bangalore",
                address="123 MG Road",
                healthians_zone_id="77",
            )
        )
    else:
        existing_participant.booking_id = "1387699587154"
        existing_participant.barcode = "1387699587154"
        existing_participant.blood_collection_time_slot_id = "STM_OLD"
        existing_participant.latitude = 12.97
        existing_participant.longitude = 77.59
        existing_participant.pincode = "560001"
        existing_participant.address = "123 MG Road"
        existing_participant.healthians_zone_id = "77"
    await test_db_session.commit()
    return slot_date


@pytest.mark.asyncio
async def test_check_serviceability_for_reschedule_allows_existing_booking(
    async_client, test_db_session
):
    await _seed_home_reschedule_fixture(test_db_session)
    auth = _auth_header(631)
    base = "/engagements/7201/console/participants/94101/book-home-collection"

    mock_geocode = AsyncMock(
        return_value=[{"latitude": 12.97, "longitude": 77.59, "state": "KA", "country": "India"}]
    )
    mock_serviceability = AsyncMock(
        return_value={"status": True, "data": {"zone_id": 77}, "message": "ok"}
    )

    with patch("modules.engagements.console.service.search_places", mock_geocode):
        with patch(
            "modules.engagements.console.service.healthians_client.check_serviceability_by_location_v2",
            mock_serviceability,
        ):
            with patch(
                "modules.engagements.console.service.healthians_client.get_access_token",
                AsyncMock(return_value="token"),
            ):
                response = await async_client.post(
                    f"{base}/check-service-availability",
                    json={
                        "address_line": "123 MG Road",
                        "city": "Bangalore",
                        "pincode": "560001",
                        "for_reschedule": True,
                    },
                    headers=auth,
                )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "serviceable"


@pytest.mark.asyncio
async def test_check_serviceability_rejects_existing_booking_without_for_reschedule(
    async_client, test_db_session
):
    await _seed_home_reschedule_fixture(test_db_session)
    auth = _auth_header(631)
    base = "/engagements/7201/console/participants/94101/book-home-collection"

    response = await async_client.post(
        f"{base}/check-service-availability",
        json={
            "address_line": "123 MG Road",
            "city": "Bangalore",
            "pincode": "560001",
        },
        headers=auth,
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "BOOKING_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_console_reschedule_success_updates_participant(async_client, test_db_session):
    slot_date = await _seed_home_reschedule_fixture(test_db_session)
    auth = _auth_header(631)
    base = "/engagements/7201/console/participants/94101/book-home-collection"

    participant = await test_db_session.get(EngagementParticipant, 97001)
    participant.blood_collection_time_slot_id = "STM96003"
    participant.engagement_date = date.fromisoformat(slot_date)
    participant.slot_start_time = time(11, 30)
    await test_db_session.commit()

    mock_reschedule = AsyncMock(
        return_value={
            "status": True,
            "message": "Booking Successfully Rescheduled.",
            "data": {"new_booking_id": "1387699589268", "refresh": ["list"]},
            "resCode": "RES0001",
            "code": 200,
        }
    )

    with patch(
        "modules.bookings.service.healthians_client.reschedule_booking_by_customer_v1",
        mock_reschedule,
    ):
        with patch(
            "modules.bookings.service.healthians_client.get_access_token",
            AsyncMock(return_value="token"),
        ):
            response = await async_client.patch(
                f"{base}/reschedule",
                json={
                    "blood_collection_date": slot_date,
                    "blood_collection_time_slot_id": "STM96003",
                    "blood_collection_time_slot": "11:30 AM",
                    "reschedule_reason": "Customer did not maintain fasting.",
                },
                headers=auth,
            )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["booking_id"] == "1387699589268"
    mock_reschedule.assert_awaited_once()
    payload = mock_reschedule.await_args.args[1]
    assert payload["booking_id"] == "1387699587154"
    assert payload["slot"] == {"slot_id": "STM96003"}
    assert payload["customers"] == [{"vendor_customer_id": "94101"}]

    participant = await test_db_session.get(EngagementParticipant, 97001)
    assert participant.booking_id == "1387699589268"
    assert participant.barcode == "1387699589268"
    assert participant.blood_collection_time_slot_id == "STM96003"


@pytest.mark.asyncio
async def test_console_reschedule_rejects_camp_collection(async_client, test_db_session):
    await _seed_home_reschedule_fixture(test_db_session)
    engagement = await test_db_session.get(Engagement, 7201)
    engagement.blood_collection_type = BloodCollectionType.camp_collection
    await test_db_session.commit()

    auth = _auth_header(631)
    response = await async_client.patch(
        "/engagements/7201/console/participants/94101/book-home-collection/reschedule",
        json={
            "blood_collection_date": date.today().isoformat(),
            "blood_collection_time_slot_id": "STM96003",
            "blood_collection_time_slot": "11:30 AM",
            "reschedule_reason": "Test",
        },
        headers=auth,
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "NOT_HOME_COLLECTION"


@pytest.mark.asyncio
async def test_console_reschedule_healthians_failure_keeps_old_booking(
    async_client, test_db_session
):
    slot_date = await _seed_home_reschedule_fixture(test_db_session)
    participant = await test_db_session.get(EngagementParticipant, 97001)
    participant.blood_collection_time_slot_id = "STM96003"
    await test_db_session.commit()

    mock_reschedule = AsyncMock(
        return_value={
            "status": False,
            "message": "Partial reschedule is not allowed for this booking.",
            "data": None,
            "code": 200,
        }
    )

    auth = _auth_header(631)
    with patch(
        "modules.bookings.service.healthians_client.reschedule_booking_by_customer_v1",
        mock_reschedule,
    ):
        with patch(
            "modules.bookings.service.healthians_client.get_access_token",
            AsyncMock(return_value="token"),
        ):
            response = await async_client.patch(
                "/engagements/7201/console/participants/94101/book-home-collection/reschedule",
                json={
                    "blood_collection_date": slot_date,
                    "blood_collection_time_slot_id": "STM96003",
                    "blood_collection_time_slot": "11:30 AM",
                    "reschedule_reason": "Test",
                },
                headers=auth,
            )

    assert response.status_code == 422
    participant = await test_db_session.get(EngagementParticipant, 97001)
    assert participant.booking_id == "1387699587154"
