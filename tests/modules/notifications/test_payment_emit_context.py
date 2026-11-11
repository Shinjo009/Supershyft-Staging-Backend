"""payments.completed emit context."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.notifications.payment_emit_context import build_payment_completed_emit_context


@pytest.mark.asyncio
async def test_payment_completed_context_includes_gift_participant_details(monkeypatch):
    order = SimpleNamespace(
        order_id=1,
        razorpay_order_id="order_test",
        amount_paise=2000,
    )
    booking = SimpleNamespace(
        user_id=20,
        metadata_={"engagement_id": 1112},
    )
    payer = SimpleNamespace(
        user_id=10,
        first_name="Booker",
        last_name="K",
        phone="9000000001",
        email="booker@example.com",
    )
    member = SimpleNamespace(
        user_id=20,
        first_name="Gift",
        last_name="Member",
        phone="9000000002",
        email="gift@example.com",
    )
    participant = SimpleNamespace(booker_relation="child", booker_message="Enjoy!")

    class _Scalars:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

        def first(self):
            return None

    class _FirstNone:
        def first(self):
            return None

    seq = iter([payer, member, _FirstNone(), payer, member, participant])

    async def fake_execute(_stmt):
        value = next(seq, None)
        if hasattr(value, "first"):
            return value
        return _Scalars(value)

    db = MagicMock()
    db.execute = AsyncMock(side_effect=fake_execute)

    ctx = await build_payment_completed_emit_context(
        db,
        order=order,
        bookings=[booking],
        payer_user_id=10,
        razorpay_payment_id="pay_test",
    )
    pd = ctx.get("participant_details") or {}
    assert pd.get("booker_name") == "Booker K"
    assert pd.get("recipient_name") == "Gift Member"
    assert pd.get("relationship") == "Child"
    assert pd.get("gift_message") == "Enjoy!"


@pytest.mark.asyncio
async def test_payment_completed_discount_code_in_payment_block(monkeypatch):
    order = SimpleNamespace(order_id=5, razorpay_order_id="order_x", amount_paise=100)
    booking = SimpleNamespace(user_id=1, metadata_={})

    async def fake_execute(stmt):
        class _R:
            def scalar_one_or_none(self):
                return None

            def first(self):
                return (SimpleNamespace(discount_paise=50), "SUPER99")

        return _R()

    db = MagicMock()
    db.execute = AsyncMock(side_effect=fake_execute)

    ctx = await build_payment_completed_emit_context(
        db,
        order=order,
        bookings=[booking],
        payer_user_id=1,
    )
    assert ctx["payment"]["discount_code"] == "SUPER99"
