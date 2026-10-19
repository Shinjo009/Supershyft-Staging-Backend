"""Auto-booking behavior for family onboard (camp vs home collection)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.modules.users.family_onboard_helpers import seed_family_onboard_platform_defaults


@pytest.mark.asyncio
async def test_family_onboard_auto_booking_set_when_slot_id_provided(async_client, test_db_session):
    await seed_family_onboard_platform_defaults(test_db_session)
    payload = {
        "booker": {
            "name": "Adi Kumar",
            "phone": "9000100301",
            "email": "adi.auto@example.com",
        },
        "members": [
            {
                "name": "Member One",
                "phone": "9000100302",
                "relation": "child",
                "age": 20,
                "blood_collection_date": "2026-04-01",
                "blood_collection_time_slot": "09:30",
                "blood_collection_time_slot_id": "slot-test-123",
            },
        ],
    }
    response = await async_client.post("/users/public/family-onboard", json=payload)
    assert response.status_code == 200
    engagement_id = response.json()["data"]["members"][0]["engagement_id"]
    row = (
        await test_db_session.execute(
            text("SELECT auto_booking FROM engagements WHERE engagement_id = :eid"),
            {"eid": engagement_id},
        )
    ).first()
    assert row is not None
    # Platform default is typically home_collection; slot id enables auto_booking.
    assert row.auto_booking is True
