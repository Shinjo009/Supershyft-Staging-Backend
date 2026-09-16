"""Tests for public B2C pay-later booking endpoints."""

from __future__ import annotations

from datetime import date, time
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from modules.engagements.models import BloodCollectionType, Engagement
from tests.modules.bookings.test_bookings_routes import _seed_healthians_diagnostic_package


_PUBLIC_CHECK_PAYLOAD = {
    "address_line": "Flat 12, Green Park",
    "landmark": "Near Mall",
    "city": "Mumbai",
    "pincode": "400001",
    "diagnostic_package_id": 1,
}


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
    assert data["engagement_code"]
    assert data["zone_id"] == "440"

    part_count = (
        await test_db_session.execute(
            text(
                "SELECT COUNT(*) FROM engagement_participants ep "
                "JOIN engagements e ON e.engagement_id = ep.engagement_id "
                "WHERE e.engagement_code = :code"
            ),
            {"code": data["engagement_code"]},
        )
    ).scalar_one()
    assert part_count == 0


@pytest.mark.asyncio
async def test_public_available_slots(async_client, test_db_session):
    await _seed_healthians_diagnostic_package(test_db_session)
    await _seed_public_draft_engagement(
        test_db_session,
        engagement_id=950101,
        engagement_code="PUB950101",
    )

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

    with (
        patch("modules.bookings.service.healthians_client.get_access_token", new_callable=AsyncMock, return_value="tok"),
        patch(
            "modules.bookings.service.healthians_client.get_slots_by_location",
            new_callable=AsyncMock,
            return_value=healthians_slots,
        ),
    ):
        response = await async_client.post(
            "/book/public/available-slots",
            json={
                "engagement_code": "PUB950101",
                "blood_collection_date": "2026-07-15",
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "success"
    assert data["engagement_code"] == "PUB950101"
    assert len(data["slots"]) == 1


@pytest.mark.asyncio
async def test_public_lock_stores_draft_slot_fields(async_client, test_db_session):
    await _seed_healthians_diagnostic_package(test_db_session)
    await _seed_public_draft_engagement(
        test_db_session,
        engagement_id=950102,
        engagement_code="PUB950102",
    )

    freeze_resp = {
        "status": True,
        "resCode": "RES0001",
        "message": "Slot locked",
        "data": {"slot_id": "34235263", "freeze_time": "30"},
    }

    with (
        patch("modules.bookings.service.healthians_client.get_access_token", new_callable=AsyncMock, return_value="tok"),
        patch(
            "modules.bookings.service.healthians_client.freeze_slot_v1",
            new_callable=AsyncMock,
            return_value=freeze_resp,
        ) as mock_freeze,
    ):
        response = await async_client.post(
            "/book/public/lock",
            json={
                "engagement_code": "PUB950102",
                "blood_collection_date": "2026-07-15",
                "blood_collection_time_slot_id": "34235263",
                "blood_collection_time_slot": "06:00:00",
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "success"
    assert data["engagement_code"] == "PUB950102"
    mock_freeze.assert_awaited_once()
    assert mock_freeze.await_args.kwargs["vendor_billing_user_id"] == "PUB950102"

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
async def test_public_onboard_book_creates_healthians_booking(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr("core.config.settings.HEALTHIANS_CHECKSUM_KEY", "test-checksum")
    await _seed_healthians_diagnostic_package(test_db_session)
    await _seed_onboard_book_prereqs(test_db_session)
    await _seed_public_draft_engagement(
        test_db_session,
        engagement_id=950103,
        engagement_code="PUB950103",
        locked=True,
    )

    payload = {
        "age": 30,
        "first_name": "Public",
        "last_name": "Booker",
        "email": "public.booker@example.com",
        "phone": "9501030000",
        "gender": "male",
        "city": "Mumbai",
        "pincode": "400001",
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
            return_value={"status": True, "booking_id": "HI950103", "message": "Booking placed"},
        ) as mock_create,
        patch(
            "modules.engagements.service.EngagementsService.notify_onboarding_assistants_after_enrollment",
            new_callable=AsyncMock,
        ),
    ):
        response = await async_client.post(
            "/users/public/onboard/book",
            json={"engagement_code": "PUB950103", **payload},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["booking_id"] == "HI950103"
    assert data["status"] == "scheduled"
    assert data["engagement_code"] == "PUB950103"
    assert data["tokens"]["access_token"]
    assert data["tokens"]["refresh_token"]
    mock_create.assert_awaited_once()
    assert mock_create.await_args.args[1]["vendor_billing_user_id"] == "PUB950103"

    participant_row = (
        await test_db_session.execute(
            text(
                "SELECT booking_id, blood_collection_time_slot_id "
                "FROM engagement_participants WHERE engagement_id = 950103"
            )
        )
    ).one()
    assert participant_row.booking_id == "HI950103"
    assert participant_row.blood_collection_time_slot_id == "slot-123"

    eng_row = (
        await test_db_session.execute(
            text(
                "SELECT status, draft_slot_id, draft_slot_date, draft_slot_time "
                "FROM engagements WHERE engagement_id = 950103"
            )
        )
    ).one()
    assert eng_row.status == "scheduled"
    assert eng_row.draft_slot_id is None
    assert eng_row.draft_slot_date is None
    assert eng_row.draft_slot_time is None


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

    payload = {
        "age": 28,
        "first_name": "Code",
        "last_name": "Booker",
        "phone": "9501040000",
        "gender": "female",
        "city": "Mumbai",
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
        ),
    ):
        response = await async_client.post(
            "/users/code/PUB950104/onboard/book",
            json=payload,
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["booking_id"] == "HI950104"
    assert data["engagement_code"] == "PUB950104"
    assert data["tokens"]["token_type"] == "bearer"
