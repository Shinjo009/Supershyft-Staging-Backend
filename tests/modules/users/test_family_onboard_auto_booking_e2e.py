"""Auto-booking behavior for family onboard respects platform settings."""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from core.config import settings
from tests.helpers.auth import user_auth_header
from tests.modules.users.family_onboard_helpers import (
    ONBOARDING_ALERT_SERVICE_KEY,
    engagement_ids_from_start,
    seed_family_onboard_b2c_onboarding_settings,
    seed_family_onboard_onboarding_notification_setup,
    seed_family_onboard_platform_defaults,
)

_FAMILY_ONBOARD_WITH_SLOT = {
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


async def _engagement_auto_booking(test_db_session, engagement_id: int) -> bool | None:
    row = (
        await test_db_session.execute(
            text("SELECT auto_booking FROM engagements WHERE engagement_id = :eid"),
            {"eid": engagement_id},
        )
    ).first()
    assert row is not None
    return row.auto_booking


@pytest.mark.asyncio
async def test_family_onboard_auto_booking_false_when_settings_no_despite_slot_id(
    async_client,
    test_db_session,
):
    await seed_family_onboard_platform_defaults(test_db_session)
    response = await async_client.post("/users/public/family-onboard", json=_FAMILY_ONBOARD_WITH_SLOT)
    assert response.status_code == 200
    engagement_id = response.json()["data"]["members"][0]["engagement_id"]
    assert await _engagement_auto_booking(test_db_session, engagement_id) is False


@pytest.mark.asyncio
async def test_family_onboard_auto_booking_true_when_settings_yes_and_slot_id(
    async_client,
    test_db_session,
):
    await seed_family_onboard_b2c_onboarding_settings(test_db_session, auto_booking=True)
    response = await async_client.post("/users/public/family-onboard", json=_FAMILY_ONBOARD_WITH_SLOT)
    assert response.status_code == 200
    engagement_id = response.json()["data"]["members"][0]["engagement_id"]
    assert await _engagement_auto_booking(test_db_session, engagement_id) is True


def _razorpay_signature(*, order_id: str, payment_id: str) -> str:
    message = f"{order_id}|{payment_id}"
    return hmac.new(
        key=settings.RAZORPAY_KEY_SECRET.encode(),
        msg=message.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()


def _mock_razorpay_order(*, amount_paise: int, receipt: str):
    return {"id": f"order_family_auto_{receipt}", "amount": amount_paise, "currency": "INR"}


def _fake_n8n_httpx_client(webhook_calls: list[dict]):
    class _FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {"accepted": True}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json=None):
            webhook_calls.append({"url": url, "json": json})
            return _FakeResponse()

    return _FakeClient


@pytest.mark.asyncio
async def test_family_onboard_auto_booking_confirm_onboarding_once(
    async_client, test_db_session, monkeypatch
):
    await seed_family_onboard_b2c_onboarding_settings(test_db_session, auto_booking=True)
    await seed_family_onboard_onboarding_notification_setup(test_db_session)
    webhook_calls: list[dict] = []

    monkeypatch.setattr(
        "modules.notifications.service.httpx.AsyncClient",
        _fake_n8n_httpx_client(webhook_calls),
    )
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test_razorpay_secret")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test")
    monkeypatch.setattr(
        "modules.payments.services._create_razorpay_order_sync",
        _mock_razorpay_order,
    )

    booker_phone = _FAMILY_ONBOARD_WITH_SLOT["booker"]["phone"]
    start_resp = await async_client.post(
        "/users/public/family-onboard",
        json=_FAMILY_ONBOARD_WITH_SLOT,
    )
    assert start_resp.status_code == 200
    start_data = start_resp.json()["data"]
    booker_user_id = start_data["booker_user_id"]
    engagement_id = start_data["members"][0]["engagement_id"]

    await test_db_session.execute(
        text(
            "UPDATE engagements SET healthians_zone_id = '440', latitude = 28.6, longitude = 77.2, "
            "address = 'Test', pincode = '110001' WHERE engagement_id = :eid"
        ),
        {"eid": engagement_id},
    )
    await test_db_session.commit()

    previous_bypass = settings.ALLOW_BYPASS_OTP
    settings.ALLOW_BYPASS_OTP = True
    try:
        verify_resp = await async_client.post(
            "/users/public/family-onboard/verify-pay",
            json={
                "phone": booker_phone,
                "otp": "654321",
                "engagement_ids": engagement_ids_from_start(start_data),
            },
        )
    finally:
        settings.ALLOW_BYPASS_OTP = previous_bypass
    assert verify_resp.status_code == 200
    order_id = verify_resp.json()["data"]["razorpay_order_id"]
    payment_id = "pay_family_auto_onboard_once"
    signature = _razorpay_signature(order_id=order_id, payment_id=payment_id)

    freeze_mock = AsyncMock(
        return_value={"status": True, "resCode": "RES0001", "message": "ok", "data": {"slot_id": "slot-test-123"}},
    )
    create_mock = AsyncMock(
        return_value={"status": True, "booking_id": "HI-FAM-AUTO-1", "message": "OK"},
    )

    with patch(
        "modules.bookings.service.healthians_client.get_access_token",
        new_callable=AsyncMock,
        return_value="tok",
    ), patch(
        "modules.bookings.service.healthians_client.freeze_slot_v1",
        freeze_mock,
    ), patch(
        "modules.bookings.service.healthians_client.create_booking_v3",
        create_mock,
    ), patch(
        "modules.users.service.UsersService._create_metsights_profile_for_engagement",
        new_callable=AsyncMock,
        return_value=None,
    ):
        confirm_resp = await async_client.post(
            "/users/public/family-onboard/confirm-payment",
            headers=user_auth_header(booker_user_id),
            json={
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": signature,
            },
        )

    assert confirm_resp.status_code == 200
    alert_calls = [c for c in webhook_calls if "booking-alert-test" in c["url"]]
    assert len(alert_calls) == 1

    rows = (
        await test_db_session.execute(
            text(
                "SELECT notification_id FROM notifications WHERE engagement_id = :eid "
                "AND service_key = :sk"
            ),
            {"eid": engagement_id, "sk": ONBOARDING_ALERT_SERVICE_KEY},
        )
    ).scalars().all()
    assert len(rows) == 1
