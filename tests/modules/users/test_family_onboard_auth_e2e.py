"""Authorization and negative paths for family onboard."""

from __future__ import annotations

import pytest

from core.config import settings
from tests.helpers.auth import user_auth_header
from tests.modules.users.family_onboard_helpers import (
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
    family_onboard_id = start_resp.json()["data"]["family_onboard_id"]

    previous_bypass = settings.ALLOW_BYPASS_OTP
    settings.ALLOW_BYPASS_OTP = False
    try:
        verify_resp = await async_client.post(
            "/users/public/family-onboard/verify-pay",
            json={
                "family_onboard_id": family_onboard_id,
                "phone": booker_phone,
                "otp": "000000",
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
    family_onboard_id = start_resp.json()["data"]["family_onboard_id"]

    confirm_resp = await async_client.post(
        "/users/public/family-onboard/confirm-payment",
        headers=user_auth_header(999999),
        json={
            "family_onboard_id": family_onboard_id,
            "razorpay_order_id": "order_x",
            "razorpay_payment_id": "pay_x",
            "razorpay_signature": "sig_x",
        },
    )
    assert confirm_resp.status_code in {401, 403, 404, 422}


@pytest.mark.asyncio
async def test_family_onboard_unknown_session_returns_404(async_client, test_db_session):
    await seed_family_onboard_platform_defaults(test_db_session)
    resp = await async_client.post(
        "/users/public/family-onboard/verify-pay",
        json={
            "family_onboard_id": "00000000-0000-0000-0000-000000000099",
            "phone": "9000100999",
            "otp": "1234",
        },
    )
    assert resp.status_code == 404
