"""Tests for paid consultation booking: /book/consultation/pay and /book/consultation."""

from __future__ import annotations

import hashlib
import hmac
from datetime import date, timedelta, time
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select, text

from core.config import settings
from modules.discounts.models import DiscountCode
from modules.engagements.enums import EngagementStatus
from modules.engagements.models import Engagement, EngagementType
from modules.experts.models import Expert, ExpertAvailabilityModel, ExpertAvailabilityOverrideModel
from modules.users.models import User
from tests.helpers.auth import user_auth_header


CONSULTATION_SLOT = "09:00"


def _consultation_pay_payload(
    *,
    user_id: int,
    expert: Expert,
    consult_date: date,
    slot: str = CONSULTATION_SLOT,
    discount_code: str | None = None,
    extra_members: list[dict] | None = None,
) -> dict:
    members = [
        {
            "user_id": user_id,
            "expert_type": expert.expert_type,
            "expert_id": expert.expert_id,
            "date": consult_date.isoformat(),
            "slot": slot,
        }
    ]
    if extra_members:
        members.extend(extra_members)
    body: dict = {"members": members}
    if discount_code is not None:
        body["discount_code"] = discount_code
    return body


def _engagement_id_from_pay(data: dict) -> int:
    return int(data["members"][0]["engagement_id"])


def _consultation_date(offset_days: int = 0) -> date:
    return date.today() + timedelta(days=14 + offset_days)


def _engagement_status(engagement: Engagement) -> str:
    status = engagement.status
    if isinstance(status, EngagementStatus):
        return status.value
    return str(status).lower()


def _auth_header(user_id: int) -> dict[str, str]:
    return user_auth_header(user_id)


def _mock_razorpay_order(*, amount_paise: int, receipt: str):
    return {"id": f"order_test_{receipt}", "amount": amount_paise, "currency": "INR"}


def _razorpay_signature(*, order_id: str, payment_id: str) -> str:
    message = f"{order_id}|{payment_id}"
    return hmac.new(
        key=settings.RAZORPAY_KEY_SECRET.encode(),
        msg=message.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()


async def _ensure_consultation_engagement_type(test_db_session) -> int:
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_types (code, display_name, is_active) "
            "VALUES ('consultation', 'Consultation', true) "
            "ON CONFLICT (code) DO NOTHING"
        )
    )
    await test_db_session.commit()
    result = await test_db_session.execute(
        text("SELECT id FROM engagement_types WHERE code = 'consultation' LIMIT 1")
    )
    return int(result.scalar_one())


async def _seed_paid_consultation_expert(
    test_db_session,
    *,
    expert_id: int | None = None,
    expert_type: str = "doctor",
    fee_paise: int = 50000,
    availability_days: tuple[int, ...] | None = None,
) -> Expert:
    if availability_days is None:
        availability_days = tuple(range(7))
    expert = Expert(
        expert_id=expert_id,
        partner_id=None,
        expert_type=expert_type,
        specialization="General Physician",
        status="active",
        appointment_fee_paise=fee_paise,
        session_duration_mins=30,
    )
    test_db_session.add(expert)
    await test_db_session.flush()
    for day in availability_days:
        test_db_session.add(
            ExpertAvailabilityModel(
                expert_id=expert.expert_id,
                day_of_week=day,
                start_time=time(9, 0),
                end_time=time(17, 0),
                slot_duration=20,
                buffer_time=5,
            )
        )
    await test_db_session.commit()
    return expert


async def _seed_user(test_db_session, user_id: int) -> None:
    test_db_session.add(
        User(
            user_id=user_id,
            age=30,
            phone=f"{user_id:010d}"[-10:],
            status="active",
            first_name="Consult",
            last_name="Payer",
            gender="male",
            city="Mumbai",
            parent_id=None,
        )
    )
    await test_db_session.commit()


async def _seed_general_discount(test_db_session, code: str = "CONSULT10") -> None:
    row = DiscountCode(
        code=code,
        name="Consult 10",
        status="active",
        discount_type="percentage",
        percent_value=Decimal("10"),
        scope_mode="general",
        package_apply_mode="all",
    )
    test_db_session.add(row)
    await test_db_session.commit()


async def _seed_package_include_discount(test_db_session, package_id: int = 1) -> None:
    from modules.discounts.models import DiscountCodePackage

    code = DiscountCode(
        code="PKGONLY",
        name="Package only",
        status="active",
        discount_type="percentage",
        percent_value=Decimal("10"),
        scope_mode="general",
        package_apply_mode="include",
    )
    test_db_session.add(code)
    await test_db_session.flush()
    test_db_session.add(
        DiscountCodePackage(
            discount_code_id=code.discount_code_id,
            diagnostic_package_id=package_id,
            mode="include",
        )
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_consultation_pay_rejects_invalid_slot(async_client, test_db_session):
    await _ensure_consultation_engagement_type(test_db_session)
    expert = await _seed_paid_consultation_expert(test_db_session)
    await _seed_user(test_db_session, 950001)

    response = await async_client.post(
        "/book/consultation/pay",
        headers=_auth_header(950001),
        json=_consultation_pay_payload(
            user_id=950001,
            expert=expert,
            consult_date=_consultation_date(),
            slot="23:59",
        ),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_consultation_pay_rejects_expert_type_mismatch(async_client, test_db_session):
    await _ensure_consultation_engagement_type(test_db_session)
    expert = await _seed_paid_consultation_expert(test_db_session, expert_type="doctor")
    await _seed_user(test_db_session, 950002)

    response = await async_client.post(
        "/book/consultation/pay",
        headers=_auth_header(950002),
        json={
            "members": [
                {
                    "user_id": 950002,
                    "expert_type": "nutritionist",
                    "expert_id": expert.expert_id,
                    "date": _consultation_date().isoformat(),
                    "slot": CONSULTATION_SLOT,
                }
            ]
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_consultation_pay_rejects_missing_fee(async_client, test_db_session):
    await _ensure_consultation_engagement_type(test_db_session)
    expert = await _seed_paid_consultation_expert(test_db_session, fee_paise=0)
    await _seed_user(test_db_session, 950003)

    response = await async_client.post(
        "/book/consultation/pay",
        headers=_auth_header(950003),
        json=_consultation_pay_payload(
            user_id=950003,
            expert=expert,
            consult_date=_consultation_date(),
        ),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_consultation_pay_creates_draft_and_razorpay_order(
    async_client, test_db_session, monkeypatch
):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test_razorpay_secret")
    await _ensure_consultation_engagement_type(test_db_session)
    expert = await _seed_paid_consultation_expert(test_db_session, fee_paise=50000)
    await _seed_user(test_db_session, 950010)
    consult_date = _consultation_date(0)

    with patch(
        "modules.payments.services._create_razorpay_order_sync",
        side_effect=_mock_razorpay_order,
    ):
        response = await async_client.post(
            "/book/consultation/pay",
            headers=_auth_header(950010),
            json=_consultation_pay_payload(
                user_id=950010,
                expert=expert,
                consult_date=consult_date,
            ),
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["members"][0]["engagement_id"]
    assert data["amount_paise"] == 50000
    assert data["razorpay_order_id"]

    eng = await test_db_session.get(Engagement, _engagement_id_from_pay(data))
    assert _engagement_status(eng) == EngagementStatus.draft.value
    type_row = await test_db_session.get(EngagementType, eng.engagement_type)
    assert type_row is not None and type_row.code == "consultation"

    hold_count = (
        await test_db_session.execute(
            select(func.count())
            .select_from(ExpertAvailabilityOverrideModel)
            .where(
                ExpertAvailabilityOverrideModel.expert_id == expert.expert_id,
                ExpertAvailabilityOverrideModel.override_date == consult_date,
            )
        )
    ).scalar_one()
    assert int(hold_count) >= 1


@pytest.mark.asyncio
async def test_consultation_pay_applies_general_discount(
    async_client, test_db_session, monkeypatch
):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test_razorpay_secret")
    await _ensure_consultation_engagement_type(test_db_session)
    expert = await _seed_paid_consultation_expert(test_db_session, fee_paise=100000)
    await _seed_user(test_db_session, 950011)
    await _seed_general_discount(test_db_session)
    consult_date = _consultation_date(1)

    with patch(
        "modules.payments.services._create_razorpay_order_sync",
        side_effect=_mock_razorpay_order,
    ):
        response = await async_client.post(
            "/book/consultation/pay",
            headers=_auth_header(950011),
            json=_consultation_pay_payload(
                user_id=950011,
                expert=expert,
                consult_date=consult_date,
                slot="09:25",
                discount_code="CONSULT10",
            ),
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["amount_paise"] == 90000
    assert data["discount"]["discount_paise"] == 10000
    assert data["discount"].get("usage_id")


@pytest.mark.asyncio
async def test_consultation_pay_rejects_package_include_discount(
    async_client, test_db_session, monkeypatch
):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test_razorpay_secret")
    await _ensure_consultation_engagement_type(test_db_session)
    expert = await _seed_paid_consultation_expert(test_db_session)
    await _seed_user(test_db_session, 950012)
    await _seed_package_include_discount(test_db_session)
    consult_date = _consultation_date(2)

    with patch(
        "modules.payments.services._create_razorpay_order_sync",
        side_effect=_mock_razorpay_order,
    ):
        response = await async_client.post(
            "/book/consultation/pay",
            headers=_auth_header(950012),
            json=_consultation_pay_payload(
                user_id=950012,
                expert=expert,
                consult_date=consult_date,
                discount_code="PKGONLY",
            ),
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_consultation_finalize_schedules_engagement(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test_razorpay_secret")
    await _ensure_consultation_engagement_type(test_db_session)
    expert = await _seed_paid_consultation_expert(test_db_session)
    await _seed_user(test_db_session, 950020)
    consult_date = _consultation_date(3)

    with patch(
        "modules.payments.services._create_razorpay_order_sync",
        side_effect=_mock_razorpay_order,
    ):
        pay_resp = await async_client.post(
            "/book/consultation/pay",
            headers=_auth_header(950020),
            json=_consultation_pay_payload(
                user_id=950020,
                expert=expert,
                consult_date=consult_date,
            ),
        )
    pay_data = pay_resp.json()["data"]
    order_id = pay_data["razorpay_order_id"]
    payment_id = "pay_consult_950020"
    signature = _razorpay_signature(order_id=order_id, payment_id=payment_id)

    with patch(
        "modules.notifications.consultation_booking_alert_notify.notify_onboarding_assistants_on_consultation_booking",
        new_callable=AsyncMock,
    ):
        book_resp = await async_client.post(
            "/book/consultation",
            headers=_auth_header(950020),
            json={
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": signature,
            },
        )

    assert book_resp.status_code == 200
    body = book_resp.json()["data"]
    assert body["payment_verified"] is True
    assert body["status"] == "scheduled"
    assert body["members"][0]["status"] == "success"

    eng = await test_db_session.get(Engagement, _engagement_id_from_pay(pay_data))
    assert _engagement_status(eng) == EngagementStatus.scheduled.value
    assert str(eng.start_date) == consult_date.isoformat()
    assert str(eng.end_date) == consult_date.isoformat()


@pytest.mark.asyncio
async def test_consultation_finalize_rejects_bad_signature(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test_razorpay_secret")
    await _ensure_consultation_engagement_type(test_db_session)
    expert = await _seed_paid_consultation_expert(test_db_session)
    await _seed_user(test_db_session, 950021)
    consult_date = _consultation_date(4)

    with patch(
        "modules.payments.services._create_razorpay_order_sync",
        side_effect=_mock_razorpay_order,
    ):
        pay_resp = await async_client.post(
            "/book/consultation/pay",
            headers=_auth_header(950021),
            json=_consultation_pay_payload(
                user_id=950021,
                expert=expert,
                consult_date=consult_date,
            ),
        )
    order_id = pay_resp.json()["data"]["razorpay_order_id"]
    engagement_id = _engagement_id_from_pay(pay_resp.json()["data"])

    book_resp = await async_client.post(
        "/book/consultation",
        headers=_auth_header(950021),
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": "pay_bad",
            "razorpay_signature": "invalid",
        },
    )
    assert book_resp.status_code == 400

    eng = await test_db_session.get(Engagement, engagement_id)
    assert _engagement_status(eng) == EngagementStatus.draft.value


@pytest.mark.asyncio
async def test_consultation_payment_failed_releases_hold_and_cancels_draft(
    async_client, test_db_session, monkeypatch
):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test_razorpay_secret")
    await _ensure_consultation_engagement_type(test_db_session)
    expert = await _seed_paid_consultation_expert(test_db_session)
    await _seed_user(test_db_session, 950030)
    consult_date = _consultation_date(5)

    with patch(
        "modules.payments.services._create_razorpay_order_sync",
        side_effect=_mock_razorpay_order,
    ):
        pay_resp = await async_client.post(
            "/book/consultation/pay",
            headers=_auth_header(950030),
            json=_consultation_pay_payload(
                user_id=950030,
                expert=expert,
                consult_date=consult_date,
            ),
        )
    pay_data = pay_resp.json()["data"]
    order_id = pay_data["razorpay_order_id"]
    engagement_id = _engagement_id_from_pay(pay_data)

    failed_resp = await async_client.post(
        "/payments/failed",
        headers=_auth_header(950030),
        json={"razorpay_order_id": order_id, "failure_reason": "dismissed"},
    )
    assert failed_resp.status_code == 200

    eng = await test_db_session.get(Engagement, engagement_id)
    assert _engagement_status(eng) == EngagementStatus.cancelled.value

    hold_count = (
        await test_db_session.execute(
            select(func.count())
            .select_from(ExpertAvailabilityOverrideModel)
            .where(
                ExpertAvailabilityOverrideModel.expert_id == expert.expert_id,
                ExpertAvailabilityOverrideModel.override_date == consult_date,
            )
        )
    ).scalar_one()
    assert int(hold_count) == 0


@pytest.mark.asyncio
async def test_consultation_pay_rejects_duplicate_user_id(async_client, test_db_session):
    await _ensure_consultation_engagement_type(test_db_session)
    expert = await _seed_paid_consultation_expert(test_db_session)
    await _seed_user(test_db_session, 950040)
    consult_date = _consultation_date(6)
    member_line = {
        "user_id": 950040,
        "expert_type": expert.expert_type,
        "expert_id": expert.expert_id,
        "date": consult_date.isoformat(),
        "slot": CONSULTATION_SLOT,
    }

    response = await async_client.post(
        "/book/consultation/pay",
        headers=_auth_header(950040),
        json={"members": [member_line, member_line]},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_consultation_pay_rejects_duplicate_slot_in_request(async_client, test_db_session):
    await _ensure_consultation_engagement_type(test_db_session)
    expert = await _seed_paid_consultation_expert(test_db_session)
    await _seed_user(test_db_session, 950041)
    test_db_session.add(
        User(
            user_id=950042,
            age=28,
            phone="9500420001",
            status="active",
            first_name="Child",
            parent_id=950041,
        )
    )
    await test_db_session.commit()
    consult_date = _consultation_date(7)

    response = await async_client.post(
        "/book/consultation/pay",
        headers=_auth_header(950041),
        json=_consultation_pay_payload(
            user_id=950041,
            expert=expert,
            consult_date=consult_date,
            extra_members=[
                {
                    "user_id": 950042,
                    "expert_type": expert.expert_type,
                    "expert_id": expert.expert_id,
                    "date": consult_date.isoformat(),
                    "slot": CONSULTATION_SLOT,
                }
            ],
        ),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_consultation_pay_forbidden_for_sub_profile_caller(async_client, test_db_session):
    await _ensure_consultation_engagement_type(test_db_session)
    expert = await _seed_paid_consultation_expert(test_db_session)
    test_db_session.add(
        User(
            user_id=950051,
            age=30,
            phone="9500510001",
            status="active",
            first_name="Parent",
        )
    )
    test_db_session.add(
        User(
            user_id=950052,
            age=10,
            phone="9500520001",
            status="active",
            first_name="Child",
            parent_id=950051,
        )
    )
    await test_db_session.commit()
    consult_date = _consultation_date(8)

    response = await async_client.post(
        "/book/consultation/pay",
        headers=_auth_header(950052),
        json=_consultation_pay_payload(
            user_id=950052,
            expert=expert,
            consult_date=consult_date,
        ),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_consultation_pay_forbidden_unrelated_member(async_client, test_db_session):
    await _ensure_consultation_engagement_type(test_db_session)
    expert = await _seed_paid_consultation_expert(test_db_session)
    await _seed_user(test_db_session, 950061)
    await _seed_user(test_db_session, 950062)
    consult_date = _consultation_date(9)

    response = await async_client.post(
        "/book/consultation/pay",
        headers=_auth_header(950061),
        json=_consultation_pay_payload(
            user_id=950062,
            expert=expert,
            consult_date=consult_date,
        ),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_consultation_pay_and_finalize_two_members(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test_razorpay_secret")
    await _ensure_consultation_engagement_type(test_db_session)
    expert = await _seed_paid_consultation_expert(test_db_session, fee_paise=50000)
    test_db_session.add(
        User(
            user_id=950070,
            age=35,
            phone="9500700001",
            status="active",
            first_name="Parent",
            city="Mumbai",
        )
    )
    test_db_session.add(
        User(
            user_id=950071,
            age=12,
            phone="9500710001",
            status="active",
            first_name="Child",
            parent_id=950070,
            city="Mumbai",
        )
    )
    await test_db_session.commit()
    consult_date = _consultation_date(10)

    with patch(
        "modules.payments.services._create_razorpay_order_sync",
        side_effect=_mock_razorpay_order,
    ):
        pay_resp = await async_client.post(
            "/book/consultation/pay",
            headers=_auth_header(950070),
            json=_consultation_pay_payload(
                user_id=950070,
                expert=expert,
                consult_date=consult_date,
                slot="09:00",
                extra_members=[
                    {
                        "user_id": 950071,
                        "expert_type": expert.expert_type,
                        "expert_id": expert.expert_id,
                        "date": consult_date.isoformat(),
                        "slot": "09:25",
                    }
                ],
            ),
        )

    assert pay_resp.status_code == 200
    pay_data = pay_resp.json()["data"]
    assert len(pay_data["booking_ids"]) == 2
    assert len(pay_data["members"]) == 2
    assert pay_data["amount_paise"] == 100000

    order_id = pay_data["razorpay_order_id"]
    payment_id = "pay_consult_950070_batch"
    signature = _razorpay_signature(order_id=order_id, payment_id=payment_id)

    with patch(
        "modules.notifications.consultation_booking_alert_notify.notify_onboarding_assistants_on_consultation_booking",
        new_callable=AsyncMock,
    ):
        book_resp = await async_client.post(
            "/book/consultation",
            headers=_auth_header(950070),
            json={
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": signature,
            },
        )

    assert book_resp.status_code == 200
    body = book_resp.json()["data"]
    assert body["payment_verified"] is True
    assert len(body["members"]) == 2
    assert all(m["status"] == "success" for m in body["members"])

    for member in pay_data["members"]:
        eng = await test_db_session.get(Engagement, member["engagement_id"])
        assert _engagement_status(eng) == EngagementStatus.scheduled.value
