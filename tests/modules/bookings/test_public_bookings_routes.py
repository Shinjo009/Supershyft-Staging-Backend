"""Tests for public B2C pay-later booking endpoints."""

from __future__ import annotations

from datetime import date, time
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from modules.engagements.models import BloodCollectionType, Engagement
from modules.users.models import User
from tests.modules.bookings.test_bookings_routes import _seed_healthians_diagnostic_package


_PUBLIC_CHECK_PAYLOAD = {
    "address_line": "Flat 12, Green Park",
    "landmark": "Near Mall",
    "city": "Mumbai",
    "pincode": "400001",
}


async def _seed_platform_default_diagnostic_package(test_db_session, *, package_id: int = 1) -> None:
    await test_db_session.execute(text("DELETE FROM platform_settings"))
    await test_db_session.execute(
        text(
            "INSERT INTO platform_settings (settings_id, b2c_default_assessment_package_id, b2c_default_diagnostic_package_id) "
            "VALUES (1, 1, :package_id)"
        ),
        {"package_id": package_id},
    )
    await test_db_session.commit()


async def _seed_public_draft_engagement(
    test_db_session,
    *,
    engagement_id: int,
    engagement_code: str,
    locked: bool = False,
) -> None:
    engagement = Engagement(
        engagement_id=engagement_id,
        engagement_name="public-draft",
        organization_id=None,
        engagement_code=engagement_code,
        diagnostic_package_id=1,
        city="Mumbai",
        address="Flat 1, Block A",
        sub_locality="Flat 1",
        pincode="400001",
        latitude=19.0760,
        longitude=72.8777,
        healthians_zone_id="440",
        slot_duration=20,
        status="draft",
        blood_collection_type=BloodCollectionType.home_collection,
    )
    if locked:
        engagement.draft_slot_id = "slot-123"
        engagement.draft_slot_date = date(2026, 7, 15)
        engagement.draft_slot_time = time(6, 0)
    test_db_session.add(engagement)
    await test_db_session.commit()


async def _seed_user(test_db_session, *, user_id: int, phone: str) -> None:
    test_db_session.add(
        User(
            user_id=user_id,
            first_name="Test",
            last_name="User",
            age=30,
            phone=phone,
            address=_PUBLIC_CHECK_PAYLOAD["address_line"],
            pin_code=_PUBLIC_CHECK_PAYLOAD["pincode"],
            city=_PUBLIC_CHECK_PAYLOAD["city"],
            status="active",
            is_participant=True,
        )
    )
    await test_db_session.commit()


async def _seed_onboard_book_prereqs(test_db_session) -> None:
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, status) "
            "VALUES (1, 'PK1', 'Package', 'active') ON CONFLICT (package_id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_types (code, display_name, is_active) "
            "VALUES ('bio_ai', 'Bio AI', true) "
            "ON CONFLICT (code) DO UPDATE SET display_name = EXCLUDED.display_name, is_active = true"
        )
    )
    await test_db_session.execute(text("DELETE FROM platform_settings"))
    await test_db_session.execute(
        text(
            "INSERT INTO platform_settings (settings_id, b2c_default_assessment_package_id, b2c_default_diagnostic_package_id) "
            "VALUES (1, 1, 1)"
        )
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_public_check_service_availability_no_auth(async_client, test_db_session):
    await _seed_healthians_diagnostic_package(test_db_session)
    await _seed_platform_default_diagnostic_package(test_db_session)

    geocode_result = [{"latitude": 19.0760, "longitude": 72.8777, "state": "Maharashtra", "country": "India"}]
    healthians_resp = {"status": True, "data": {"zone_id": "440"}, "message": "Serviceable"}

    with (
        patch("modules.bookings.service.search_places", new_callable=AsyncMock, return_value=geocode_result),
        patch("modules.bookings.service.healthians_client.get_access_token", new_callable=AsyncMock, return_value="tok"),
        patch(
            "modules.bookings.service.healthians_client.check_serviceability_by_location_v2",
            new_callable=AsyncMock,
            return_value=healthians_resp,
        ),
    ):
        response = await async_client.post(
            "/book/public/check-service-availability",
            json=_PUBLIC_CHECK_PAYLOAD,
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "serviceable"
    assert data["zone_id"] == "440"
    assert "engagement_code" not in data

    eng_count = (
        await test_db_session.execute(
            text("SELECT COUNT(*) FROM engagements WHERE engagement_name = 'public-draft'")
        )
    ).scalar_one()
    assert eng_count == 0


@pytest.mark.asyncio
async def test_code_check_service_availability_uses_engagement_package(async_client, test_db_session):
    await _seed_healthians_diagnostic_package(test_db_session, package_id=2)
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package "
            "(diagnostic_package_id, reference_id, package_name, diagnostic_provider, status, price, external_package_id) "
            "VALUES (2, 'REF-H2', 'Healthians Package 2', 'healthians', 'active', 500, 102) "
            "ON CONFLICT (diagnostic_package_id) DO UPDATE SET "
            "diagnostic_provider = EXCLUDED.diagnostic_provider, external_package_id = EXCLUDED.external_package_id"
        )
    )
    await test_db_session.commit()

    engagement = Engagement(
        engagement_id=950150,
        engagement_name="camp-engagement",
        organization_id=None,
        engagement_code="CAMP950150",
        diagnostic_package_id=2,
        city="Mumbai",
        address="Old address",
        sub_locality="Old address",
        pincode="400001",
        slot_duration=20,
        status="scheduled",
        blood_collection_type=BloodCollectionType.home_collection,
    )
    test_db_session.add(engagement)
    await test_db_session.commit()

    geocode_result = [{"latitude": 19.0760, "longitude": 72.8777, "state": "Maharashtra", "country": "India"}]
    healthians_resp = {"status": True, "data": {"zone_id": "441"}, "message": "Serviceable"}

    with (
        patch("modules.bookings.service.search_places", new_callable=AsyncMock, return_value=geocode_result),
        patch("modules.bookings.service.healthians_client.get_access_token", new_callable=AsyncMock, return_value="tok"),
        patch(
            "modules.bookings.service.healthians_client.check_serviceability_by_location_v2",
            new_callable=AsyncMock,
            return_value=healthians_resp,
        ),
    ):
        response = await async_client.post(
            "/book/code/CAMP950150/check-service-availability",
            json=_PUBLIC_CHECK_PAYLOAD,
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "serviceable"
    assert data["engagement_code"] == "CAMP950150"
    assert data["zone_id"] == "441"

    eng_row = (
        await test_db_session.execute(
            text(
                "SELECT diagnostic_package_id, address, healthians_zone_id, status "
                "FROM engagements WHERE engagement_code = 'CAMP950150'"
            )
        )
    ).one()
    assert eng_row.diagnostic_package_id == 2
    assert eng_row.address == "Old address"
    assert eng_row.healthians_zone_id is None
    assert eng_row.status == "scheduled"


@pytest.mark.asyncio
async def test_public_available_slots_stateless(async_client, test_db_session):
    await _seed_healthians_diagnostic_package(test_db_session)
    await _seed_platform_default_diagnostic_package(test_db_session)

    geocode_result = [{"latitude": 19.0760, "longitude": 72.8777, "state": "Maharashtra", "country": "India"}]
    healthians_slots = {
        "status": True,
        "data": [
            {
                "end_time": "07:00:00",
                "slot_date": "2026-07-15",
                "slot_time": "06:00:00",
                "stm_id": "45418464",
            }
        ],
    }

    healthians_check = {"status": True, "data": {"zone_id": "440"}, "message": "Serviceable"}

    with (
        patch("modules.bookings.service.search_places", new_callable=AsyncMock, return_value=geocode_result),
        patch("modules.bookings.service.healthians_client.get_access_token", new_callable=AsyncMock, return_value="tok"),
        patch(
            "modules.bookings.service.healthians_client.check_serviceability_by_location_v2",
            new_callable=AsyncMock,
            return_value=healthians_check,
        ),
        patch(
            "modules.bookings.service.healthians_client.get_slots_by_location",
            new_callable=AsyncMock,
            return_value=healthians_slots,
        ) as mock_slots,
    ):
        response = await async_client.post(
            "/book/public/available-slots",
            json={
                "address_line": _PUBLIC_CHECK_PAYLOAD["address_line"],
                "city": _PUBLIC_CHECK_PAYLOAD["city"],
                "pincode": _PUBLIC_CHECK_PAYLOAD["pincode"],
                "blood_collection_date": "2026-07-15",
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "success"
    assert "engagement_code" not in data
    assert len(data["slots"]) == 1
    mock_slots.assert_awaited_once()
    assert mock_slots.await_args.args[1]["zone_id"] == "440"


@pytest.mark.asyncio
async def test_code_available_slots_uses_engagement_package(async_client, test_db_session):
    await _seed_healthians_diagnostic_package(test_db_session, package_id=2)
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package "
            "(diagnostic_package_id, reference_id, package_name, diagnostic_provider, status, price, external_package_id) "
            "VALUES (2, 'REF-H2', 'Healthians Package 2', 'healthians', 'active', 500, 102) "
            "ON CONFLICT (diagnostic_package_id) DO UPDATE SET "
            "diagnostic_provider = EXCLUDED.diagnostic_provider, external_package_id = EXCLUDED.external_package_id"
        )
    )
    await test_db_session.commit()

    engagement = Engagement(
        engagement_id=950151,
        engagement_name="camp-engagement",
        organization_id=None,
        engagement_code="CAMP950151",
        diagnostic_package_id=2,
        city="Mumbai",
        address="Flat 1",
        sub_locality="Flat 1",
        pincode="400001",
        latitude=19.0760,
        longitude=72.8777,
        healthians_zone_id="441",
        slot_duration=20,
        status="scheduled",
        blood_collection_type=BloodCollectionType.home_collection,
    )
    test_db_session.add(engagement)
    await test_db_session.commit()

    geocode_result = [{"latitude": 19.0760, "longitude": 72.8777, "state": "Maharashtra", "country": "India"}]
    healthians_check = {"status": True, "data": {"zone_id": "441"}, "message": "Serviceable"}
    healthians_slots = {
        "status": True,
        "data": [
            {
                "end_time": "08:00:00",
                "slot_date": "2026-07-16",
                "slot_time": "07:00:00",
                "stm_id": "45418465",
            }
        ],
    }

    with (
        patch("modules.bookings.service.search_places", new_callable=AsyncMock, return_value=geocode_result),
        patch("modules.bookings.service.healthians_client.get_access_token", new_callable=AsyncMock, return_value="tok"),
        patch(
            "modules.bookings.service.healthians_client.check_serviceability_by_location_v2",
            new_callable=AsyncMock,
            return_value=healthians_check,
        ),
        patch(
            "modules.bookings.service.healthians_client.get_slots_by_location",
            new_callable=AsyncMock,
            return_value=healthians_slots,
        ) as mock_slots,
    ):
        response = await async_client.post(
            "/book/code/CAMP950151/available-slots",
            json={
                "address_line": _PUBLIC_CHECK_PAYLOAD["address_line"],
                "city": _PUBLIC_CHECK_PAYLOAD["city"],
                "pincode": _PUBLIC_CHECK_PAYLOAD["pincode"],
                "blood_collection_date": "2026-07-16",
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "success"
    assert data["engagement_code"] == "CAMP950151"
    assert len(data["slots"]) == 1
    mock_slots.assert_awaited_once()
    assert mock_slots.await_args.args[1]["package"] == [{"deal_id": ["package_102"]}]
    assert mock_slots.await_args.args[1]["zone_id"] == "441"


@pytest.mark.asyncio
async def test_public_lock_stateless_uses_user_id_vendor(async_client, test_db_session):
    await _seed_user(test_db_session, user_id=950101, phone="9501010000")
    geocode_result = [{"latitude": 19.0760, "longitude": 72.8777, "state": "Maharashtra", "country": "India"}]
    healthians_check = {"status": True, "data": {"zone_id": "440"}, "message": "Serviceable"}
    freeze_resp = {
        "status": True,
        "resCode": "RES0001",
        "message": "Slot locked",
        "data": {"slot_id": "34235263", "freeze_time": "30"},
    }

    with (
        patch("modules.bookings.service.search_places", new_callable=AsyncMock, return_value=geocode_result),
        patch("modules.bookings.service.healthians_client.get_access_token", new_callable=AsyncMock, return_value="tok"),
        patch(
            "modules.bookings.service.healthians_client.check_serviceability_by_location_v2",
            new_callable=AsyncMock,
            return_value=healthians_check,
        ),
        patch(
            "modules.bookings.service.healthians_client.freeze_slot_v1",
            new_callable=AsyncMock,
            return_value=freeze_resp,
        ) as mock_freeze,
    ):
        response = await async_client.post(
            "/book/public/lock",
            json={
                "address_line": _PUBLIC_CHECK_PAYLOAD["address_line"],
                "city": _PUBLIC_CHECK_PAYLOAD["city"],
                "pincode": _PUBLIC_CHECK_PAYLOAD["pincode"],
                "user_id": 950101,
                "blood_collection_date": "2026-07-15",
                "blood_collection_time_slot_id": "34235263",
                "blood_collection_time_slot": "06:00:00",
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "success"
    assert data["vendor_billing_user_id"] == "950101"
    assert data["zone_id"] == "440"
    mock_freeze.assert_awaited_once()
    assert mock_freeze.await_args.kwargs["vendor_billing_user_id"] == "950101"


@pytest.mark.asyncio
async def test_code_lock_stores_draft_slot_fields(async_client, test_db_session):
    await _seed_healthians_diagnostic_package(test_db_session)
    await _seed_user(test_db_session, user_id=950102, phone="9501020000")
    await _seed_public_draft_engagement(
        test_db_session,
        engagement_id=950102,
        engagement_code="PUB950102",
    )

    geocode_result = [{"latitude": 19.0760, "longitude": 72.8777, "state": "Maharashtra", "country": "India"}]
    healthians_check = {"status": True, "data": {"zone_id": "440"}, "message": "Serviceable"}
    freeze_resp = {
        "status": True,
        "resCode": "RES0001",
        "message": "Slot locked",
        "data": {"slot_id": "34235263", "freeze_time": "30"},
    }

    with (
        patch("modules.bookings.service.search_places", new_callable=AsyncMock, return_value=geocode_result),
        patch("modules.bookings.service.healthians_client.get_access_token", new_callable=AsyncMock, return_value="tok"),
        patch(
            "modules.bookings.service.healthians_client.check_serviceability_by_location_v2",
            new_callable=AsyncMock,
            return_value=healthians_check,
        ),
        patch(
            "modules.bookings.service.healthians_client.freeze_slot_v1",
            new_callable=AsyncMock,
            return_value=freeze_resp,
        ) as mock_freeze,
    ):
        response = await async_client.post(
            "/book/code/PUB950102/lock",
            json={
                "address_line": _PUBLIC_CHECK_PAYLOAD["address_line"],
                "city": _PUBLIC_CHECK_PAYLOAD["city"],
                "pincode": _PUBLIC_CHECK_PAYLOAD["pincode"],
                "user_id": 950102,
                "blood_collection_date": "2026-07-15",
                "blood_collection_time_slot_id": "34235263",
                "blood_collection_time_slot": "06:00:00",
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "success"
    assert data["engagement_code"] == "PUB950102"
    assert data["vendor_billing_user_id"] == "950102"
    assert data["zone_id"] == "440"
    mock_freeze.assert_awaited_once()
    assert mock_freeze.await_args.kwargs["vendor_billing_user_id"] == "950102"

    eng_row = (
        await test_db_session.execute(
            text(
                "SELECT draft_slot_id, draft_slot_date, draft_slot_time "
                "FROM engagements WHERE engagement_code = 'PUB950102'"
            )
        )
    ).one()
    assert eng_row.draft_slot_id == "34235263"
    assert str(eng_row.draft_slot_date) == "2026-07-15"
    assert str(eng_row.draft_slot_time) == "06:00:00"


@pytest.mark.asyncio
async def test_public_onboard_book_creates_engagement_and_healthians_booking(
    async_client, test_db_session, monkeypatch
):
    monkeypatch.setattr("core.config.settings.HEALTHIANS_CHECKSUM_KEY", "test-checksum")
    await _seed_healthians_diagnostic_package(test_db_session)
    await _seed_onboard_book_prereqs(test_db_session)
    await _seed_user(test_db_session, user_id=950103, phone="9501030000")

    payload = {
        "user_id": 950103,
        "blood_collection_date": "2026-07-15",
        "blood_collection_time_slot_id": "34235263",
        "blood_collection_time_slot": "06:00:00",
    }

    geocode_result = [{"latitude": 19.0760, "longitude": 72.8777, "state": "Maharashtra", "country": "India"}]
    healthians_check = {"status": True, "data": {"zone_id": "440"}, "message": "Serviceable"}

    with (
        patch("modules.bookings.service.search_places", new_callable=AsyncMock, return_value=geocode_result),
        patch(
            "modules.bookings.service.healthians_client.get_access_token",
            new_callable=AsyncMock,
            return_value="tok",
        ),
        patch(
            "modules.bookings.service.healthians_client.check_serviceability_by_location_v2",
            new_callable=AsyncMock,
            return_value=healthians_check,
        ),
        patch(
            "modules.bookings.service.healthians_client.create_booking_v3",
            new_callable=AsyncMock,
            return_value={"status": True, "booking_id": "HI950103", "message": "Booking placed"},
        ) as mock_create,
        patch(
            "modules.engagements.service.EngagementsService.notify_onboarding_assistants_after_enrollment",
            new_callable=AsyncMock,
        ) as mock_notify,
    ):
        response = await async_client.post("/users/public/onboard/book", json=payload)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["booking_id"] == "HI950103"
    assert data["status"] == "scheduled"
    assert data["engagement_code"]
    assert "tokens" not in data
    mock_create.assert_awaited_once()
    assert mock_create.await_args.args[1]["vendor_billing_user_id"] == str(data["user_id"])
    mock_notify.assert_awaited()

    participant_row = (
        await test_db_session.execute(
            text(
                "SELECT booking_id, blood_collection_time_slot_id "
                "FROM engagement_participants WHERE engagement_id = :engagement_id"
            ),
            {"engagement_id": data["engagement_id"]},
        )
    ).one()
    assert participant_row.booking_id == "HI950103"
    assert participant_row.blood_collection_time_slot_id == "34235263"

    eng_row = (
        await test_db_session.execute(
            text(
                "SELECT status, organization_id, healthians_zone_id, draft_slot_id "
                "FROM engagements WHERE engagement_id = :engagement_id"
            ),
            {"engagement_id": data["engagement_id"]},
        )
    ).one()
    assert eng_row.status == "scheduled"
    assert eng_row.organization_id is None
    assert eng_row.healthians_zone_id == "440"
    assert eng_row.draft_slot_id is None


@pytest.mark.asyncio
async def test_public_e2e_check_slots_lock_onboard_book(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr("core.config.settings.HEALTHIANS_CHECKSUM_KEY", "test-checksum")
    await _seed_healthians_diagnostic_package(test_db_session)
    await _seed_onboard_book_prereqs(test_db_session)
    await _seed_user(test_db_session, user_id=950199, phone="9501990000")

    geocode_result = [{"latitude": 19.0760, "longitude": 72.8777, "state": "Maharashtra", "country": "India"}]
    healthians_check = {"status": True, "data": {"zone_id": "440"}, "message": "Serviceable"}
    healthians_slots = {
        "status": True,
        "data": [{"end_time": "07:00:00", "slot_date": "2026-07-15", "slot_time": "06:00:00", "stm_id": "45418464"}],
    }
    freeze_resp = {
        "status": True,
        "resCode": "RES0001",
        "message": "Slot locked",
        "data": {"slot_id": "45418464", "freeze_time": "30"},
    }
    book_resp = {"status": True, "booking_id": "HI-E2E-PUB", "message": "Booking placed"}

    with (
        patch("modules.bookings.service.search_places", new_callable=AsyncMock, return_value=geocode_result),
        patch("modules.bookings.service.healthians_client.get_access_token", new_callable=AsyncMock, return_value="tok"),
        patch(
            "modules.bookings.service.healthians_client.check_serviceability_by_location_v2",
            new_callable=AsyncMock,
            return_value=healthians_check,
        ),
        patch(
            "modules.bookings.service.healthians_client.get_slots_by_location",
            new_callable=AsyncMock,
            return_value=healthians_slots,
        ),
        patch(
            "modules.bookings.service.healthians_client.freeze_slot_v1",
            new_callable=AsyncMock,
            return_value=freeze_resp,
        ) as mock_freeze,
        patch(
            "modules.bookings.service.healthians_client.create_booking_v3",
            new_callable=AsyncMock,
            return_value=book_resp,
        ) as mock_create,
        patch(
            "modules.engagements.service.EngagementsService.notify_onboarding_assistants_after_enrollment",
            new_callable=AsyncMock,
        ),
    ):
        check = await async_client.post("/book/public/check-service-availability", json=_PUBLIC_CHECK_PAYLOAD)
        assert check.json()["data"]["zone_id"] == "440"

        slots = await async_client.post(
            "/book/public/available-slots",
            json={
                "address_line": _PUBLIC_CHECK_PAYLOAD["address_line"],
                "city": _PUBLIC_CHECK_PAYLOAD["city"],
                "pincode": _PUBLIC_CHECK_PAYLOAD["pincode"],
                "blood_collection_date": "2026-07-15",
            },
        )
        assert slots.json()["data"]["status"] == "success"

        lock = await async_client.post(
            "/book/public/lock",
            json={
                "address_line": _PUBLIC_CHECK_PAYLOAD["address_line"],
                "city": _PUBLIC_CHECK_PAYLOAD["city"],
                "pincode": _PUBLIC_CHECK_PAYLOAD["pincode"],
                "user_id": 950199,
                "blood_collection_date": "2026-07-15",
                "blood_collection_time_slot_id": "45418464",
                "blood_collection_time_slot": "06:00:00",
            },
        )
        assert lock.json()["data"]["vendor_billing_user_id"] == "950199"

        onboard = await async_client.post(
            "/users/public/onboard/book",
            json={
                "user_id": 950199,
                "blood_collection_date": "2026-07-15",
                "blood_collection_time_slot_id": "45418464",
                "blood_collection_time_slot": "06:00:00",
            },
        )

    assert onboard.status_code == 200
    assert onboard.json()["data"]["booking_id"] == "HI-E2E-PUB"
    assert onboard.json()["data"]["engagement_id"]
    mock_freeze.assert_awaited_once()
    mock_create.assert_awaited_once()
    assert mock_create.await_args.args[1]["vendor_billing_user_id"] == "950199"


@pytest.mark.asyncio
async def test_code_onboard_book_endpoint(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr("core.config.settings.HEALTHIANS_CHECKSUM_KEY", "test-checksum")
    await _seed_healthians_diagnostic_package(test_db_session)
    await _seed_onboard_book_prereqs(test_db_session)
    await _seed_public_draft_engagement(
        test_db_session,
        engagement_id=950104,
        engagement_code="PUB950104",
        locked=True,
    )
    await _seed_user(test_db_session, user_id=950104, phone="9501040000")

    payload = {
        "user_id": 950104,
        "blood_collection_date": "2026-07-15",
        "blood_collection_time_slot_id": "slot-123",
        "blood_collection_time_slot": "06:00:00",
    }

    with (
        patch(
            "modules.bookings.service.healthians_client.get_access_token",
            new_callable=AsyncMock,
            return_value="tok",
        ),
        patch(
            "modules.bookings.service.healthians_client.create_booking_v3",
            new_callable=AsyncMock,
            return_value={"status": True, "booking_id": "HI950104", "message": "OK"},
        ),
        patch(
            "modules.engagements.service.EngagementsService.notify_onboarding_assistants_after_enrollment",
            new_callable=AsyncMock,
        ) as mock_notify,
    ):
        response = await async_client.post(
            "/users/code/PUB950104/onboard/book",
            json=payload,
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["booking_id"] == "HI950104"
    assert data["engagement_code"] == "PUB950104"
    assert "tokens" not in data
    eng_status = (
        await test_db_session.execute(
            text("SELECT status FROM engagements WHERE engagement_code = 'PUB950104'")
        )
    ).scalar_one()
    assert eng_status == "draft"
    mock_notify.assert_awaited()


@pytest.mark.asyncio
async def test_code_e2e_check_slots_lock_onboard_book(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr("core.config.settings.HEALTHIANS_CHECKSUM_KEY", "test-checksum")
    await _seed_healthians_diagnostic_package(test_db_session)
    await _seed_onboard_book_prereqs(test_db_session)
    await _seed_user(test_db_session, user_id=950105, phone="9501050000")

    engagement = Engagement(
        engagement_id=950105,
        engagement_name="camp-code-e2e",
        organization_id=None,
        engagement_code="CAMP950105",
        diagnostic_package_id=1,
        assessment_package_id=1,
        city="Mumbai",
        address="Flat 1",
        sub_locality="Flat 1",
        pincode="400001",
        latitude=19.0760,
        longitude=72.8777,
        healthians_zone_id="440",
        slot_duration=20,
        status="scheduled",
        blood_collection_type=BloodCollectionType.home_collection,
    )
    test_db_session.add(engagement)
    await test_db_session.commit()

    geocode_result = [{"latitude": 19.0760, "longitude": 72.8777, "state": "Maharashtra", "country": "India"}]
    healthians_check = {"status": True, "data": {"zone_id": "440"}, "message": "Serviceable"}
    healthians_slots = {
        "status": True,
        "data": [{"end_time": "08:00:00", "slot_date": "2026-07-16", "slot_time": "07:00:00", "stm_id": "45418465"}],
    }
    freeze_resp = {
        "status": True,
        "resCode": "RES0001",
        "message": "Slot locked",
        "data": {"slot_id": "45418465", "freeze_time": "30"},
    }
    book_resp = {"status": True, "booking_id": "HI-E2E-CODE", "message": "OK"}

    with (
        patch("modules.bookings.service.search_places", new_callable=AsyncMock, return_value=geocode_result),
        patch("modules.bookings.service.healthians_client.get_access_token", new_callable=AsyncMock, return_value="tok"),
        patch(
            "modules.bookings.service.healthians_client.check_serviceability_by_location_v2",
            new_callable=AsyncMock,
            return_value=healthians_check,
        ),
        patch(
            "modules.bookings.service.healthians_client.get_slots_by_location",
            new_callable=AsyncMock,
            return_value=healthians_slots,
        ),
        patch(
            "modules.bookings.service.healthians_client.freeze_slot_v1",
            new_callable=AsyncMock,
            return_value=freeze_resp,
        ),
        patch(
            "modules.bookings.service.healthians_client.create_booking_v3",
            new_callable=AsyncMock,
            return_value=book_resp,
        ) as mock_create,
        patch(
            "modules.engagements.service.EngagementsService.notify_onboarding_assistants_after_enrollment",
            new_callable=AsyncMock,
        ) as mock_notify,
    ):
        check = await async_client.post(
            "/book/code/CAMP950105/check-service-availability",
            json=_PUBLIC_CHECK_PAYLOAD,
        )
        assert check.json()["data"]["status"] == "serviceable"

        slots = await async_client.post(
            "/book/code/CAMP950105/available-slots",
            json={
                "address_line": _PUBLIC_CHECK_PAYLOAD["address_line"],
                "city": _PUBLIC_CHECK_PAYLOAD["city"],
                "pincode": _PUBLIC_CHECK_PAYLOAD["pincode"],
                "blood_collection_date": "2026-07-16",
            },
        )
        assert slots.json()["data"]["status"] == "success"

        lock = await async_client.post(
            "/book/code/CAMP950105/lock",
            json={
                "address_line": _PUBLIC_CHECK_PAYLOAD["address_line"],
                "city": _PUBLIC_CHECK_PAYLOAD["city"],
                "pincode": _PUBLIC_CHECK_PAYLOAD["pincode"],
                "user_id": 950105,
                "blood_collection_date": "2026-07-16",
                "blood_collection_time_slot_id": "45418465",
                "blood_collection_time_slot": "07:00:00",
            },
        )
        assert lock.json()["data"]["status"] == "success"

        onboard = await async_client.post(
            "/users/code/CAMP950105/onboard/book",
            json={
                "user_id": 950105,
                "blood_collection_date": "2026-07-16",
                "blood_collection_time_slot_id": "45418465",
                "blood_collection_time_slot": "07:00:00",
            },
        )

    assert onboard.status_code == 200
    assert onboard.json()["data"]["booking_id"] == "HI-E2E-CODE"
    eng_status = (
        await test_db_session.execute(
            text("SELECT status FROM engagements WHERE engagement_code = 'CAMP950105'")
        )
    ).scalar_one()
    assert eng_status == "scheduled"
    mock_create.assert_awaited_once()
    assert mock_create.await_args.args[1]["vendor_billing_user_id"] == "950105"
    mock_notify.assert_awaited()


@pytest.mark.asyncio
async def test_code_onboard_book_assigns_assessment_even_when_booking_fails(
    async_client, test_db_session, monkeypatch
):
    """Regression: booking failure after enroll must not leave journey with 0 assessments."""
    monkeypatch.setattr("core.config.settings.HEALTHIANS_CHECKSUM_KEY", "test-checksum")
    await _seed_healthians_diagnostic_package(test_db_session)
    await _seed_onboard_book_prereqs(test_db_session)
    await _seed_user(test_db_session, user_id=950206, phone="9502060000")

    engagement = Engagement(
        engagement_id=950206,
        engagement_name="camp-code-assess-heal",
        organization_id=None,
        engagement_code="CAMP950206",
        diagnostic_package_id=1,
        assessment_package_id=1,
        city="Mumbai",
        address="Flat 1",
        sub_locality="Flat 1",
        pincode="400001",
        latitude=19.0760,
        longitude=72.8777,
        healthians_zone_id="440",
        slot_duration=20,
        status="running",
        blood_collection_type=BloodCollectionType.home_collection,
    )
    test_db_session.add(engagement)
    await test_db_session.commit()

    payload = {
        "user_id": 950206,
        "blood_collection_date": "2026-07-16",
        "blood_collection_time_slot_id": "slot-fail-1",
        "blood_collection_time_slot": "07:00:00",
    }

    with (
        patch(
            "modules.bookings.service.healthians_client.get_access_token",
            new_callable=AsyncMock,
            return_value="tok",
        ),
        patch(
            "modules.bookings.service.healthians_client.create_booking_v3",
            new_callable=AsyncMock,
            return_value={"status": False, "message": "Please enter sub_locality."},
        ),
        patch(
            "modules.engagements.service.EngagementsService.notify_onboarding_assistants_after_enrollment",
            new_callable=AsyncMock,
        ),
    ):
        first = await async_client.post("/users/code/CAMP950206/onboard/book", json=payload)

    assert first.status_code == 422
    assert first.json()["error_code"] == "BOOKING_FAILED"

    enrolled = (
        await test_db_session.execute(
            text(
                "SELECT COUNT(*) FROM engagement_participants "
                "WHERE engagement_id = 950206 AND user_id = 950206"
            )
        )
    ).scalar_one()
    assert enrolled == 1

    instances = (
        await test_db_session.execute(
            text(
                "SELECT COUNT(*) FROM assessment_instances "
                "WHERE engagement_id = 950206 AND user_id = 950206 AND package_id = 1"
            )
        )
    ).scalar_one()
    assert instances == 1

    with (
        patch(
            "modules.bookings.service.healthians_client.get_access_token",
            new_callable=AsyncMock,
            return_value="tok",
        ),
        patch(
            "modules.bookings.service.healthians_client.create_booking_v3",
            new_callable=AsyncMock,
            return_value={"status": True, "booking_id": "HI950206", "message": "OK"},
        ),
        patch(
            "modules.engagements.service.EngagementsService.notify_onboarding_assistants_after_enrollment",
            new_callable=AsyncMock,
        ),
    ):
        second = await async_client.post("/users/code/CAMP950206/onboard/book", json=payload)

    assert second.status_code == 200
    assert second.json()["data"]["booking_id"] == "HI950206"
    assert second.json()["data"]["assessment_instance_id"] is not None
