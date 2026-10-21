"""E2E pay funnel for family onboard verify-pay and confirm-payment."""

from __future__ import annotations

import hashlib
import hmac

import pytest
from sqlalchemy import text

from core.config import settings
from tests.helpers.auth import user_auth_header
from tests.modules.users.family_onboard_helpers import (
    engagement_ids_from_start,
    engagement_status_is,
    family_onboard_start_payload,
    seed_family_onboard_platform_defaults,
)


def _mock_razorpay_order(*, amount_paise: int, receipt: str):
    return {"id": f"order_family_{receipt}", "amount": amount_paise, "currency": "INR"}


def _razorpay_signature(*, order_id: str, payment_id: str) -> str:
    message = f"{order_id}|{payment_id}"
    return hmac.new(
        key=settings.RAZORPAY_KEY_SECRET.encode(),
        msg=message.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()


@pytest.mark.asyncio
async def test_family_onboard_pay_funnel(async_client, test_db_session, monkeypatch):
    await seed_family_onboard_platform_defaults(test_db_session)
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test_razorpay_secret")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test")
    monkeypatch.setattr(
        "modules.payments.services._create_razorpay_order_sync",
        _mock_razorpay_order,
    )

    booker_phone = "9000100101"
    start_resp = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(
            booker_phone=booker_phone,
            member_phone="9000100102",
            second_member_phone="9000100103",
        ),
    )
    assert start_resp.status_code == 200
    start_data = start_resp.json()["data"]
    booker_user_id = start_data["booker_user_id"]

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
    verify_data = verify_resp.json()["data"]
    order_id = verify_data["razorpay_order_id"]
    assert order_id
    assert verify_data.get("tokens", {}).get("access_token")
    assert verify_data.get("engagement_ids") == engagement_ids_from_start(start_data)

    for member in start_data["members"]:
        row = (
            await test_db_session.execute(
                text(
                    "SELECT ep.paid, e.status AS engagement_status "
                    "FROM engagement_participants ep "
                    "JOIN engagements e ON e.engagement_id = ep.engagement_id "
                    "WHERE ep.engagement_participant_id = :pid"
                ),
                {"pid": member["engagement_participant_id"]},
            )
        ).first()
        assert row.paid is False
        assert engagement_status_is(row.engagement_status, "draft")

    payment_id = "pay_family_test_1"
    signature = _razorpay_signature(order_id=order_id, payment_id=payment_id)
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

    for member in start_data["members"]:
        row = (
            await test_db_session.execute(
                text(
                    "SELECT ep.paid, e.status AS engagement_status "
                    "FROM engagement_participants ep "
                    "JOIN engagements e ON e.engagement_id = ep.engagement_id "
                    "WHERE ep.engagement_participant_id = :pid"
                ),
                {"pid": member["engagement_participant_id"]},
            )
        ).first()
        assert row.paid is True
        assert engagement_status_is(row.engagement_status, "scheduled")


@pytest.mark.asyncio
async def test_family_onboard_verify_pay_scoped_to_engagement_ids(async_client, test_db_session, monkeypatch):
    await seed_family_onboard_platform_defaults(test_db_session)
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test_razorpay_secret")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test")
    monkeypatch.setattr(
        "modules.payments.services._create_razorpay_order_sync",
        _mock_razorpay_order,
    )

    booker_phone = "9000100501"
    first_start = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(booker_phone=booker_phone, member_phone="9000100502"),
    )
    assert first_start.status_code == 200
    second_start = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(booker_phone=booker_phone, member_phone="9000100503"),
    )
    assert second_start.status_code == 200
    second_data = second_start.json()["data"]
    second_engagement_id = second_data["members"][0]["engagement_id"]

    previous_bypass = settings.ALLOW_BYPASS_OTP
    settings.ALLOW_BYPASS_OTP = True
    try:
        verify_resp = await async_client.post(
            "/users/public/family-onboard/verify-pay",
            json={
                "phone": booker_phone,
                "otp": "654321",
                "engagement_ids": [second_engagement_id],
            },
        )
    finally:
        settings.ALLOW_BYPASS_OTP = previous_bypass

    assert verify_resp.status_code == 200
    verify_data = verify_resp.json()["data"]
    assert len(verify_data.get("members") or []) == 1
    assert verify_data["members"][0]["engagement_id"] == second_engagement_id
    assert verify_data["engagement_ids"] == [second_engagement_id]


@pytest.mark.asyncio
async def test_family_onboard_verify_pay_forbidden_for_other_booker_engagement(
    async_client, test_db_session,
):
    await seed_family_onboard_platform_defaults(test_db_session)
    other_start = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(
            booker_phone="9000100601",
            member_phone="9000100602",
            booker_email="other.booker@example.com",
        ),
    )
    assert other_start.status_code == 200
    other_engagement_id = other_start.json()["data"]["members"][0]["engagement_id"]

    my_start = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(
            booker_phone="9000100603",
            member_phone="9000100604",
            booker_email="my.booker@example.com",
        ),
    )
    assert my_start.status_code == 200
    my_phone = "9000100603"

    previous_bypass = settings.ALLOW_BYPASS_OTP
    settings.ALLOW_BYPASS_OTP = True
    try:
        verify_resp = await async_client.post(
            "/users/public/family-onboard/verify-pay",
            json={
                "phone": my_phone,
                "otp": "654321",
                "engagement_ids": [other_engagement_id],
            },
        )
    finally:
        settings.ALLOW_BYPASS_OTP = previous_bypass

    assert verify_resp.status_code == 403
    assert verify_resp.json().get("error_code") == "FORBIDDEN"


@pytest.mark.asyncio
async def test_family_onboard_verify_pay_rejects_non_draft_engagement(async_client, test_db_session):
    await seed_family_onboard_platform_defaults(test_db_session)
    booker_phone = "9000100701"
    start_resp = await async_client.post(
        "/users/public/family-onboard",
        json=family_onboard_start_payload(booker_phone=booker_phone, member_phone="9000100702"),
    )
    assert start_resp.status_code == 200
    start_data = start_resp.json()["data"]
    engagement_id = start_data["members"][0]["engagement_id"]

    await test_db_session.execute(
        text("UPDATE engagements SET status = 2 WHERE engagement_id = :eid"),
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
                "engagement_ids": [engagement_id],
            },
        )
    finally:
        settings.ALLOW_BYPASS_OTP = previous_bypass

    assert verify_resp.status_code == 422
    assert verify_resp.json().get("error_code") == "INVALID_STATE"
