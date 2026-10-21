"""Partner slot freeze + lab order on B2B onboard and family confirm-payment."""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from core.config import settings
from tests.helpers.auth import user_auth_header
from tests.modules.users.family_onboard_helpers import (
    engagement_status_is,
    seed_family_onboard_platform_defaults,
)


def _razorpay_signature(*, order_id: str, payment_id: str) -> str:
    message = f"{order_id}|{payment_id}"
    return hmac.new(
        key=settings.RAZORPAY_KEY_SECRET.encode(),
        msg=message.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()


def _mock_razorpay_order(*, amount_paise: int, receipt: str):
    return {"id": f"order_ob_{receipt}", "amount": amount_paise, "currency": "INR"}


@pytest.mark.asyncio
async def test_b2b_onboard_group_paid_triggers_fulfill_auto_booking(async_client, test_db_session):
    from datetime import date

    from modules.engagements.enums import EngagementPaymentType
    from modules.engagements.models import BloodCollectionType, Engagement

    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, status) "
            "VALUES (1, 'PK1', 'Package', 1) ON CONFLICT (package_id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package "
            "(diagnostic_package_id, reference_id, package_name, diagnostic_provider, status, external_package_code) "
            "VALUES (1, 'REF1', 'Diag', 'healthians', 1, '101') "
            "ON CONFLICT (diagnostic_package_id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO organizations (organization_id, name, status) "
            "VALUES (8101, 'Org AutoBook', 1)"
        )
    )
    test_db_session.add(
        Engagement(
            engagement_id=3101,
            engagement_name="Auto Camp",
            engagement_code="ENGAUTO01",
            organization_id=8101,
            engagement_type=1,
            assessment_package_id=1,
            diagnostic_package_id=1,
            city="BLR",
            slot_duration=20,
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 1),
            status="running",
            payment_type=EngagementPaymentType.paid_by_group,
            auto_booking=True,
            blood_collection_type=BloodCollectionType.home_collection,
            create_profile_on_metsights=False,
            healthians_zone_id="440",
        )
    )
    await test_db_session.commit()

    fulfill_mock = AsyncMock(return_value=[{"status": "success"}])
    with patch(
        "modules.bookings.service.fulfill_auto_partner_booking_for_members",
        fulfill_mock,
    ), patch(
        "modules.users.service.UsersService._create_metsights_profile_for_engagement",
        new_callable=AsyncMock,
        return_value=None,
    ):
        response = await async_client.post(
            "/users/code/ENGAUTO01/onboard",
            json={
                "age": 30,
                "first_name": "Auto",
                "last_name": "Book",
                "phone": "8888800001",
                "email": "autobook@example.com",
                "city": "BLR",
                "blood_collection_date": "2026-02-01",
                "blood_collection_time_slot": "11:00",
                "blood_collection_time_slot_id": "stm-999",
            },
        )

    assert response.status_code == 200
    fulfill_mock.assert_awaited_once()
    call_kwargs = fulfill_mock.await_args.kwargs
    assert call_kwargs["members"][0]["engagement_id"] == 3101


@pytest.mark.asyncio
async def test_family_onboard_confirm_payment_freezes_when_auto_booking(
    async_client, test_db_session, monkeypatch,
):
    await seed_family_onboard_platform_defaults(test_db_session)
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test_razorpay_secret")
    monkeypatch.setattr(settings, "HEALTHIANS_CHECKSUM_KEY", "test-checksum")
    monkeypatch.setattr(
        "modules.payments.services._create_razorpay_order_sync",
        _mock_razorpay_order,
    )

    booker_phone = "9000100401"
    start_resp = await async_client.post(
        "/users/public/family-onboard",
        json={
            "booker": {
                "name": "Adi Kumar",
                "phone": booker_phone,
                "email": "adi.freeze@example.com",
            },
            "members": [
                {
                    "name": "Member Freeze",
                    "phone": "9000100402",
                    "relation": "child",
                    "age": 28,
                    "gender": "Male",
                    "blood_collection_date": "2026-03-15",
                    "blood_collection_time_slot": "10:00",
                    "blood_collection_time_slot_id": "stm-family-1",
                    "pincode": "110001",
                    "address": "Test address",
                },
            ],
        },
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
            },
        )
    finally:
        settings.ALLOW_BYPASS_OTP = previous_bypass

    assert verify_resp.status_code == 200
    order_id = verify_resp.json()["data"]["razorpay_order_id"]
    payment_id = "pay_family_freeze_1"
    signature = _razorpay_signature(order_id=order_id, payment_id=payment_id)

    freeze_mock = AsyncMock(
        return_value={"status": True, "resCode": "RES0001", "message": "ok", "data": {"slot_id": "stm-family-1"}},
    )
    create_mock = AsyncMock(
        return_value={"status": True, "booking_id": "HI-FAM-1", "message": "OK"},
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
    freeze_mock.assert_awaited()
    create_mock.assert_awaited()

    status_row = (
        await test_db_session.execute(
            text("SELECT status FROM engagements WHERE engagement_id = :eid"),
            {"eid": engagement_id},
        )
    ).first()
    assert engagement_status_is(status_row.status, "scheduled")
