"""Tests for PATCH /engagements/{engagement_id}/reschedule (user blood-collection)."""

from __future__ import annotations

from datetime import date, time

import pytest
from sqlalchemy import text

from modules.engagements.models import BloodCollectionType, Engagement, EngagementParticipant
from modules.users.models import User
from tests.helpers.auth import employee_auth_header, seed_employee, user_auth_header
from tests.modules.users.test_users_onboard_slot_routes import (
    _engagement_type_id,
    _onboard_payload,
    _seed_employee,
    _seed_organization,
    _seed_packages,
    _slot_detail,
)


@pytest.fixture(autouse=True)
def _bypass_schedule_cutoff(monkeypatch):
    """Existing cases use historical fixture dates; cutoff is covered in unit tests."""
    monkeypatch.setattr(
        "modules.engagements.service.ensure_schedule_change_allowed",
        lambda *args, **kwargs: None,
    )


async def _seed_packages_for_engagement(test_db_session, *, package_id: int):
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, status) "
            "VALUES (:pid, :pcode, :dname, 'active') ON CONFLICT (package_id) DO UPDATE SET "
            "package_code = EXCLUDED.package_code, display_name = EXCLUDED.display_name, status = EXCLUDED.status"
        ),
        {"pid": package_id, "pcode": f"PKG{package_id}", "dname": f"Package {package_id}"},
    )
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, reference_id, package_name, diagnostic_provider, status, bookings_count) "
            "VALUES (:did, :ref, :pname, 'test_provider', 'active', 0) ON CONFLICT (diagnostic_package_id) DO UPDATE SET "
            "reference_id = EXCLUDED.reference_id, package_name = EXCLUDED.package_name, "
            "diagnostic_provider = EXCLUDED.diagnostic_provider, status = EXCLUDED.status"
        ),
        {"did": package_id, "ref": f"REF{package_id}", "pname": f"Diag {package_id}"},
    )
    await test_db_session.commit()


async def _create_slot_engagement(
    async_client,
    test_db_session,
    *,
    user_id: int,
    employee_id: int,
    organization_id: int,
    code: str,
    capacity: int = 6,
):
    await _seed_employee(test_db_session, user_id=user_id, employee_id=employee_id)
    await _seed_organization(test_db_session, organization_id=organization_id, name=f"Org {organization_id}")
    await _seed_packages(test_db_session, package_id=organization_id)
    type_id = await _engagement_type_id(test_db_session, "bio_ai")
    response = await async_client.post(
        "/engagements",
        headers=employee_auth_header(employee_id),
        json={
            "engagement_name": f"Camp {code}",
            "organization_id": organization_id,
            "engagement_type": type_id,
            "assessment_package_id": organization_id,
            "diagnostic_package_id": organization_id,
            "city": "BLR",
            "slot_duration": 30,
            "start_date": "2026-08-20",
            "end_date": "2026-08-21",
            "engagement_code": code,
            "slot_detail": _slot_detail(capacity=capacity),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["engagement_id"]


@pytest.mark.asyncio
async def test_reschedule_with_cabin_updates_participant(async_client, test_db_session):
    engagement_id = await _create_slot_engagement(
        async_client,
        test_db_session,
        user_id=79901,
        employee_id=901,
        organization_id=9901,
        code="RESCHED1",
    )
    onboard = await async_client.post(
        "/users/code/RESCHED1/onboard",
        json=_onboard_payload(phone="9901000001", slot="09:00"),
    )
    assert onboard.status_code == 200, onboard.text
    user_id = onboard.json()["data"]["user_id"]

    response = await async_client.patch(
        f"/engagements/{engagement_id}/reschedule",
        headers=user_auth_header(user_id),
        json={
            "blood_collection_date": "2026-08-20",
            "blood_collection_time_slot": "09:30",
            "blood_collection_cabin": "blood_test_cabin_1",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["engagement_date"] == "2026-08-20"
    assert data["slot_start_time"] == "09:30:00"
    assert data["blood_collection_cabin"] == "blood_test_cabin_1"
    assert data["user_id"] == user_id


@pytest.mark.asyncio
async def test_reschedule_rejects_invalid_slot(async_client, test_db_session):
    engagement_id = await _create_slot_engagement(
        async_client,
        test_db_session,
        user_id=79902,
        employee_id=902,
        organization_id=9902,
        code="RESCHED2",
    )
    onboard = await async_client.post(
        "/users/code/RESCHED2/onboard",
        json=_onboard_payload(phone="9902000001", slot="09:00"),
    )
    assert onboard.status_code == 200, onboard.text
    user_id = onboard.json()["data"]["user_id"]

    response = await async_client.patch(
        f"/engagements/{engagement_id}/reschedule",
        headers=user_auth_header(user_id),
        json={
            "blood_collection_date": "2026-08-21",
            "blood_collection_time_slot": "09:00",
            "blood_collection_cabin": "blood_test_cabin_1",
        },
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "SLOT_UNAVAILABLE"
    assert body["message"] == "No such Slot Available"


@pytest.mark.asyncio
async def test_reschedule_allows_same_slot_when_at_capacity(async_client, test_db_session):
    engagement_id = await _create_slot_engagement(
        async_client,
        test_db_session,
        user_id=79903,
        employee_id=903,
        organization_id=9903,
        code="RESCHED3",
        capacity=1,
    )
    onboard = await async_client.post(
        "/users/code/RESCHED3/onboard",
        json=_onboard_payload(phone="9903000001", slot="09:00"),
    )
    assert onboard.status_code == 200, onboard.text
    user_id = onboard.json()["data"]["user_id"]

    response = await async_client.patch(
        f"/engagements/{engagement_id}/reschedule",
        headers=user_auth_header(user_id),
        json={
            "blood_collection_date": "2026-08-20",
            "blood_collection_time_slot": "09:00",
            "blood_collection_cabin": "blood_test_cabin_1",
        },
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_reschedule_without_cabin_updates_date_within_range(async_client, test_db_session):
    engagement_id = await _create_slot_engagement(
        async_client,
        test_db_session,
        user_id=79904,
        employee_id=904,
        organization_id=9904,
        code="RESCHED4",
    )
    onboard = await async_client.post(
        "/users/code/RESCHED4/onboard",
        json=_onboard_payload(phone="9904000001", slot="09:00"),
    )
    assert onboard.status_code == 200, onboard.text
    user_id = onboard.json()["data"]["user_id"]

    response = await async_client.patch(
        f"/engagements/{engagement_id}/reschedule",
        headers=user_auth_header(user_id),
        json={
            "blood_collection_date": "2026-08-21",
            "blood_collection_time_slot": "10:00",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["engagement_date"] == "2026-08-21"
    assert data["slot_start_time"] == "10:00:00"
    assert data["blood_collection_cabin"] == "blood_test_cabin_1"


@pytest.mark.asyncio
async def test_reschedule_without_cabin_rejects_date_outside_range(async_client, test_db_session):
    engagement_id = await _create_slot_engagement(
        async_client,
        test_db_session,
        user_id=79905,
        employee_id=905,
        organization_id=9905,
        code="RESCHED5",
    )
    onboard = await async_client.post(
        "/users/code/RESCHED5/onboard",
        json=_onboard_payload(phone="9905000001", slot="09:00"),
    )
    assert onboard.status_code == 200, onboard.text
    user_id = onboard.json()["data"]["user_id"]

    response = await async_client.patch(
        f"/engagements/{engagement_id}/reschedule",
        headers=user_auth_header(user_id),
        json={
            "blood_collection_date": "2026-08-22",
            "blood_collection_time_slot": "09:00",
        },
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_reschedule_rejects_non_participant(async_client, test_db_session):
    engagement_id = await _create_slot_engagement(
        async_client,
        test_db_session,
        user_id=79906,
        employee_id=906,
        organization_id=9906,
        code="RESCHED6",
    )
    onboard = await async_client.post(
        "/users/code/RESCHED6/onboard",
        json=_onboard_payload(phone="9906000001", slot="09:00"),
    )
    assert onboard.status_code == 200, onboard.text

    outsider = User(user_id=99062, age=30, phone="9906000002", status="active")
    test_db_session.add(outsider)
    await test_db_session.commit()

    response = await async_client.patch(
        f"/engagements/{engagement_id}/reschedule",
        headers=user_auth_header(99062),
        json={
            "blood_collection_date": "2026-08-20",
            "blood_collection_time_slot": "09:30",
            "blood_collection_cabin": "blood_test_cabin_1",
        },
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "ACCESS_DENIED"


@pytest.mark.asyncio
async def test_reschedule_with_cabin_skips_validation_when_slot_detail_null(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=907)
    await _seed_organization(test_db_session, organization_id=9907, name="No Slot Org")
    await _seed_packages_for_engagement(test_db_session, package_id=9907)
    type_id = await _engagement_type_id(test_db_session, "bio_ai")

    created = await async_client.post(
        "/engagements",
        headers=employee_auth_header(907),
        json={
            "engagement_name": "No Slot Camp",
            "organization_id": 9907,
            "engagement_type": type_id,
            "assessment_package_id": 9907,
            "diagnostic_package_id": 9907,
            "city": "BLR",
            "slot_duration": 30,
            "start_date": "2026-08-20",
            "end_date": "2026-08-21",
            "engagement_code": "RESCHED7",
        },
    )
    assert created.status_code == 201, created.text
    engagement_id = created.json()["data"]["engagement_id"]

    payload = _onboard_payload(phone="9907000001", slot="09:00")
    payload.pop("blood_collection_cabin")
    onboard = await async_client.post("/users/code/RESCHED7/onboard", json=payload)
    assert onboard.status_code == 200, onboard.text
    user_id = onboard.json()["data"]["user_id"]

    response = await async_client.patch(
        f"/engagements/{engagement_id}/reschedule",
        headers=user_auth_header(user_id),
        json={
            "blood_collection_date": "2026-08-20",
            "blood_collection_time_slot": "11:15",
            "blood_collection_cabin": "any_cabin_key",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["slot_start_time"] == "11:15:00"
    assert data["blood_collection_cabin"] == "any_cabin_key"


@pytest.mark.asyncio
async def test_reschedule_rejects_home_collection(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=908)
    await _seed_organization(test_db_session, organization_id=9908, name="Home Org Resched")
    await _seed_packages_for_engagement(test_db_session, package_id=9908)
    type_id = await _engagement_type_id(test_db_session, "bio_ai")

    test_db_session.add(User(user_id=99081, age=30, phone="99081000000", status="active"))
    await test_db_session.flush()

    test_db_session.add(
        Engagement(
            engagement_id=9908,
            engagement_name="Home Collection Reschedule",
            organization_id=9908,
            engagement_code="RESCHED8",
            engagement_type=type_id,
            assessment_package_id=9908,
            diagnostic_package_id=9908,
            city="BLR",
            slot_duration=30,
            start_date=date(2026, 8, 20),
            end_date=date(2026, 8, 20),
            status="running",
            blood_collection_type=BloodCollectionType.home_collection,
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        EngagementParticipant(
            engagement_participant_id=99081,
            engagement_id=9908,
            user_id=99081,
            engagement_date=date(2026, 8, 20),
            slot_start_time=time(9, 0),
        )
    )
    await test_db_session.commit()

    response = await async_client.patch(
        "/engagements/9908/reschedule",
        headers=user_auth_header(99081),
        json={
            "blood_collection_date": "2026-08-20",
            "blood_collection_time_slot": "09:30",
            "blood_collection_cabin": "blood_test_cabin_1",
        },
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "SCHEDULE_UPDATE_NOT_ALLOWED"
