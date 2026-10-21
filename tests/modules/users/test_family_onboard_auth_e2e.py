"""Authorization and negative paths for family onboard."""

from __future__ import annotations

import pytest

from core.config import settings
from tests.helpers.auth import user_auth_header
from tests.modules.users.family_onboard_helpers import (
    engagement_ids_from_start,
    family_onboard_start_payload,
    seed_family_onboard_platform_defaults,
)


@pytest.mark.asyncio
async def test_family_onboard_verify_pay_wrong_otp(async_client, test_db_session):
    await seed_family_onboard_platform_defaults(test_db_session)
    booker_phone = "9000100201"
    start_resp = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(booker_phone=booker_phone, member_phone="9000100202"),
    )
    assert start_resp.status_code == 200
    engagement_ids = engagement_ids_from_start(start_resp.json()["data"])
    previous_bypass = settings.ALLOW_BYPASS_OTP
    settings.ALLOW_BYPASS_OTP = False
    try:
        verify_resp = await async_client.post(
            "/users/public/family-onboard/verify-pay",
            json={
                "phone": booker_phone,
                "otp": "000000",
                "engagement_ids": engagement_ids,
            },
        )
    finally:
        settings.ALLOW_BYPASS_OTP = previous_bypass

    assert verify_resp.status_code in {400, 401, 422}


@pytest.mark.asyncio
async def test_family_onboard_confirm_forbidden_for_other_user(async_client, test_db_session):
    await seed_family_onboard_platform_defaults(test_db_session)
    start_resp = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(),
    )
    confirm_resp = await async_client.post(
        "/users/public/family-onboard/confirm-payment",
        headers=user_auth_header(999999),
        json={
            "razorpay_order_id": "order_x",
            "razorpay_payment_id": "pay_x",
            "razorpay_signature": "sig_x",
        },
    )
    assert confirm_resp.status_code in {401, 403, 404, 422}


@pytest.mark.asyncio
async def test_family_onboard_verify_pay_rejects_already_paid_engagement(async_client, test_db_session):
    from sqlalchemy import text

    await seed_family_onboard_platform_defaults(test_db_session)
    booker_phone = "9000100301"
    start_resp = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(booker_phone=booker_phone, member_phone="9000100302"),
    )
    assert start_resp.status_code == 200
    start_data = start_resp.json()["data"]
    booker_user_id = start_data["booker_user_id"]
    engagement_ids = engagement_ids_from_start(start_data)
    await test_db_session.execute(
        text(
            "UPDATE engagement_participants SET paid = true "
            "WHERE booked_by_user_id = :bid AND paid = false"
        ),
        {"bid": booker_user_id},
    )
    await test_db_session.commit()

    previous_bypass = settings.ALLOW_BYPASS_OTP
    settings.ALLOW_BYPASS_OTP = True
    try:
        resp = await async_client.post(
            "/users/public/family-onboard/verify-pay",
            json={
                "phone": booker_phone,
                "otp": "654321",
                "engagement_ids": engagement_ids,
            },
        )
    finally:
        settings.ALLOW_BYPASS_OTP = previous_bypass
    assert resp.status_code == 422
    assert resp.json().get("error_code") == "ALREADY_PAID"


@pytest.mark.asyncio
async def test_family_onboard_verify_pay_requires_engagement_ids(async_client, test_db_session):
    await seed_family_onboard_platform_defaults(test_db_session)
    previous_bypass = settings.ALLOW_BYPASS_OTP
    settings.ALLOW_BYPASS_OTP = True
    try:
        resp = await async_client.post(
            "/users/public/family-onboard/verify-pay",
            json={
                "phone": "9000100801",
                "otp": "654321",
            },
        )
    finally:
        settings.ALLOW_BYPASS_OTP = previous_bypass
    assert resp.status_code in {400, 422}
