"""Matching-role staff login: discovery + role-scoped partner OTP."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from common.subject_otp import hash_otp
from core.config import settings
from modules.partners.models import PartnerAuthOtpSession
from tests.helpers.auth import employee_auth_header, seed_employee, seed_partner


async def _seed_partner_otp(db, partner_id: int, otp: str = "654321") -> None:
    secret = settings.get_otp_hmac_secret()
    now = datetime.now(timezone.utc)
    db.add(
        PartnerAuthOtpSession(
            partner_id=partner_id,
            otp_hash=hash_otp(otp, secret),
            otp_expires_at=now + timedelta(minutes=5),
            created_at=now,
            failed_attempts=0,
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_eligible_roles_zero_one_many(async_client, test_db_session):
    phone = "8801000001"
    empty = await async_client.post("/staff/auth/eligible-roles", json={"phone": phone})
    assert empty.status_code == 200, empty.text
    assert empty.json()["data"]["roles"] == []

    await seed_employee(test_db_session, employee_id=8801, role="admin", phone=phone)
    one = await async_client.post("/staff/auth/eligible-roles", json={"phone": phone})
    assert one.status_code == 200, one.text
    roles = one.json()["data"]["roles"]
    assert len(roles) == 1
    assert roles[0] == {"kind": "employee", "role": "employee", "label": "Employee"}

    await seed_partner(
        test_db_session, partner_id=8811, role="author", phone=phone, name="Auth"
    )
    await seed_partner(
        test_db_session, partner_id=8812, role="phlebo", phone=phone, name="Ph"
    )
    many = await async_client.post("/staff/auth/eligible-roles", json={"phone": phone})
    assert many.status_code == 200, many.text
    labels = [r["label"] for r in many.json()["data"]["roles"]]
    assert labels == ["Employee", "Phlebo", "Author"]
    assert "Partner" not in labels
    for row in many.json()["data"]["roles"]:
        assert set(row.keys()) == {"kind", "role", "label"}


@pytest.mark.asyncio
async def test_eligible_roles_omits_inactive(async_client, test_db_session):
    phone = "8802000001"
    await seed_employee(
        test_db_session, employee_id=8802, role="admin", phone=phone, status="inactive"
    )
    await seed_partner(
        test_db_session,
        partner_id=8821,
        role="expert",
        phone=phone,
        status="inactive",
        name="Inactive Expert",
    )
    await seed_partner(
        test_db_session, partner_id=8822, role="author", phone=phone, name="Active Author"
    )
    res = await async_client.post("/staff/auth/eligible-roles", json={"phone": phone})
    assert res.status_code == 200, res.text
    roles = res.json()["data"]["roles"]
    assert len(roles) == 1
    assert roles[0]["role"] == "author"


@pytest.mark.asyncio
async def test_partner_otp_requires_role_and_is_role_scoped(
    async_client, test_db_session, monkeypatch
):
    phone = "8803000001"
    await seed_partner(
        test_db_session, partner_id=8831, role="phlebo", phone=phone, name="Phlebo"
    )
    await seed_partner(
        test_db_session, partner_id=8832, role="author", phone=phone, name="Author"
    )

    missing_role = await async_client.post(
        "/partners/auth/send-otp", json={"phone": phone}
    )
    assert missing_role.status_code in {400, 422}
    assert "role" in missing_role.text.lower()

    otp = "654321"
    monkeypatch.setattr(settings, "ALLOW_BYPASS_OTP", True, raising=False)
    monkeypatch.setattr(settings, "BYPASS_OTP", otp, raising=False)

    send = await async_client.post(
        "/partners/auth/send-otp",
        json={"phone": phone, "role": "author"},
    )
    assert send.status_code == 200, send.text
    await _seed_partner_otp(test_db_session, 8832, otp)

    wrong = await async_client.post(
        "/partners/auth/verify-otp",
        json={"phone": phone, "role": "phlebo", "otp": otp},
    )
    assert wrong.status_code == 401

    ok = await async_client.post(
        "/partners/auth/verify-otp",
        json={"phone": phone, "role": "author", "otp": otp},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["partner_id"] == 8832
    assert ok.json()["data"]["role"] == "author"


@pytest.mark.asyncio
async def test_production_rejects_bypass_and_dontsendotp(monkeypatch):
    from common.subject_otp import global_bypass_allowed, per_phone_bypass_allowed

    monkeypatch.setattr(settings, "APP_ENVIRONMENT", "production", raising=False)
    monkeypatch.setattr(settings, "ALLOW_BYPASS_OTP", True, raising=False)
    monkeypatch.setattr(settings, "BYPASS_OTP", "654321", raising=False)
    monkeypatch.setattr(settings, "BYPASS_OTP_BY_PHONE", "8804000001:111111", raising=False)
    settings._bypass_otp_cache_key = None
    settings._bypass_otp_by_phone_index = {}

    assert global_bypass_allowed("654321") is False
    assert per_phone_bypass_allowed(["8804000001", "+918804000001"], "111111") is False


@pytest.mark.asyncio
async def test_create_all_roles_same_phone_then_duplicate_fails(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=8840, role="admin", phone="8805000099")
    headers = employee_auth_header(8840)
    phone = "8805000001"

    emp = await async_client.post(
        "/employees",
        headers=headers,
        json={"name": "Emp Same", "phone": phone, "role": "admin"},
    )
    assert emp.status_code in {200, 201}, emp.text

    for role, label in (
        ("phlebo", "Phlebo One"),
        ("organization_manager", "Org Manager One"),
        ("author", "Author One"),
    ):
        res = await async_client.post(
            "/partners",
            headers=headers,
            json={"name": label, "phone": phone, "role": role},
        )
        assert res.status_code in {200, 201}, res.text

    dup = await async_client.post(
        "/partners",
        headers=headers,
        json={"name": "Dup Author", "phone": phone, "role": "author"},
    )
    assert dup.status_code == 409
    assert "Author" in dup.json()["message"]


@pytest.mark.asyncio
async def test_deactivated_after_discovery_blocks_verify(
    async_client, test_db_session, monkeypatch
):
    phone = "8806000001"
    partner = await seed_partner(
        test_db_session, partner_id=8861, role="phlebo", phone=phone, name="Soon Inactive"
    )
    otp = "654321"
    monkeypatch.setattr(settings, "ALLOW_BYPASS_OTP", True, raising=False)
    monkeypatch.setattr(settings, "BYPASS_OTP", otp, raising=False)

    send = await async_client.post(
        "/partners/auth/send-otp",
        json={"phone": phone, "role": "phlebo"},
    )
    assert send.status_code == 200, send.text
    await _seed_partner_otp(test_db_session, partner.partner_id, otp)

    partner.status = "inactive"
    await test_db_session.commit()

    verify = await async_client.post(
        "/partners/auth/verify-otp",
        json={"phone": phone, "role": "phlebo", "otp": otp},
    )
    assert verify.status_code == 401
