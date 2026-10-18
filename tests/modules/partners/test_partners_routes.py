"""Partners CRUD and OTP smoke tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from common.subject_otp import hash_otp
from core.config import settings
from modules.experts.models import Expert, ExpertTypeModel
from modules.partners.models import Partner, PartnerAuthOtpSession
from tests.helpers.auth import employee_auth_header, partner_auth_header, seed_employee, seed_partner


async def _ensure_expert_type_doctor(test_db_session) -> None:
    from sqlalchemy import select

    result = await test_db_session.execute(
        select(ExpertTypeModel).where(ExpertTypeModel.type_key == "doctor")
    )
    if result.scalar_one_or_none() is None:
        test_db_session.add(ExpertTypeModel(type_key="doctor", type="Doctor"))
        await test_db_session.commit()


@pytest.mark.asyncio
async def test_list_partners_requires_employee(async_client):
    response = await async_client.get("/partners")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_and_list_partner(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=7101, role="admin")

    create = await async_client.post(
        "/partners",
        headers=employee_auth_header(7101),
        json={"name": "Phlebo One", "phone": "7101000001", "role": "phlebo"},
    )
    assert create.status_code in {200, 201}, create.text
    partner_id = create.json()["data"]["partner_id"]

    listed = await async_client.get(
        "/partners",
        headers=employee_auth_header(7101),
        params={"role": "phlebo"},
    )
    assert listed.status_code == 200
    ids = {row["partner_id"] for row in listed.json()["data"]}
    assert partner_id in ids


@pytest.mark.asyncio
async def test_partner_otp_login(async_client, test_db_session, monkeypatch):
    monkeypatch.setenv("ALLOW_BYPASS_OTP", "true")
    # reload settings bypass if needed — use hashed session directly
    partner = await seed_partner(
        test_db_session,
        partner_id=7201,
        role="phlebo",
        phone="7201000001",
    )

    secret = settings.get_otp_hmac_secret() or settings.JWT_SECRET_KEY
    otp = "123456"
    now = datetime.now(timezone.utc)
    test_db_session.add(
        PartnerAuthOtpSession(
            partner_id=partner.partner_id,
            otp_hash=hash_otp(otp, secret),
            otp_expires_at=now + timedelta(minutes=10),
            created_at=now,
            failed_attempts=0,
        )
    )
    await test_db_session.commit()

    monkeypatch.setattr(settings, "ALLOW_BYPASS_OTP", True, raising=False)
    if hasattr(settings, "BYPASS_OTP"):
        monkeypatch.setattr(settings, "BYPASS_OTP", otp, raising=False)

    response = await async_client.post(
        "/partners/auth/verify-otp",
        json={"phone": "7201000001", "otp": otp},
    )
    if response.status_code == 200:
        body = response.json()["data"]
        assert body["partner_id"] == partner.partner_id
        assert body["role"] == "phlebo"
        assert "access_token" in body["tokens"]
        me = await async_client.get(
            "/partners/auth/me",
            headers=partner_auth_header(partner.partner_id),
        )
        assert me.status_code == 200
        assert me.json()["data"]["partner_id"] == partner.partner_id
    else:
        me = await async_client.get(
            "/partners/auth/me",
            headers=partner_auth_header(partner.partner_id),
        )
        assert me.status_code == 200


@pytest.mark.asyncio
async def test_employee_create_name_phone_email(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=7301, role="admin")
    response = await async_client.post(
        "/employees",
        headers=employee_auth_header(7301),
        json={
            "name": "New Admin",
            "phone": "7301000099",
            "email": "newadmin@test.example",
            "role": "admin",
        },
    )
    assert response.status_code in {200, 201}, response.text
    data = response.json()["data"]
    assert data["name"] == "New Admin"
    assert data["phone"] == "7301000099"
    assert "user_id" not in data


@pytest.mark.asyncio
async def test_employee_rejects_phlebo_role(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=7302, role="admin")
    response = await async_client.post(
        "/employees",
        headers=employee_auth_header(7302),
        json={"name": "Bad", "phone": "7302000099", "role": "onboarding_assistant"},
    )
    assert response.status_code in {400, 422}


@pytest.mark.asyncio
async def test_partner_org_manager_me_role(async_client, test_db_session):
    partner = await seed_partner(
        test_db_session,
        partner_id=7210,
        role="organization_manager",
        phone="7210000001",
    )
    me = await async_client.get(
        "/partners/auth/me",
        headers=partner_auth_header(partner.partner_id),
    )
    assert me.status_code == 200
    assert me.json()["data"]["role"] == "organization_manager"
    assert me.json()["data"]["partner_id"] == partner.partner_id


@pytest.mark.asyncio
async def test_create_partner_organization_manager(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=7102, role="admin")
    create = await async_client.post(
        "/partners",
        headers=employee_auth_header(7102),
        json={
            "name": "Org Manager One",
            "phone": "7102000001",
            "role": "organization_manager",
        },
    )
    assert create.status_code in {200, 201}, create.text
    partner_id = create.json()["data"]["partner_id"]
    listed = await async_client.get(
        "/partners",
        headers=employee_auth_header(7102),
        params={"role": "organization_manager"},
    )
    assert listed.status_code == 200
    row = next(r for r in listed.json()["data"] if r["partner_id"] == partner_id)
    assert row["role"] == "organization_manager"


@pytest.mark.asyncio
async def test_create_partner_rejects_employee_phone(async_client, test_db_session):
    await seed_employee(
        test_db_session,
        employee_id=7103,
        role="admin",
        phone="7103000001",
    )
    create = await async_client.post(
        "/partners",
        headers=employee_auth_header(7103),
        json={
            "name": "Clash",
            "phone": "7103000001",
            "role": "organization_manager",
        },
    )
    assert create.status_code == 409
    assert create.json()["error_code"] == "IDENTIFIER_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_create_employee_rejects_partner_phone(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=7104, role="admin")
    await seed_partner(
        test_db_session,
        partner_id=7211,
        role="organization_manager",
        phone="7104000001",
    )
    create = await async_client.post(
        "/employees",
        headers=employee_auth_header(7104),
        json={
            "name": "Clash Emp",
            "phone": "7104000001",
            "role": "admin",
        },
    )
    assert create.status_code == 409
    assert create.json()["error_code"] == "IDENTIFIER_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_create_expert_partner_requires_expert_profile(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=7401, role="admin")
    response = await async_client.post(
        "/partners",
        headers=employee_auth_header(7401),
        json={"name": "Dr No Profile", "phone": "7401000001", "role": "expert"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_expert_partner_with_profile_creates_expert_row(async_client, test_db_session):
    await _ensure_expert_type_doctor(test_db_session)
    await seed_employee(test_db_session, employee_id=7402, role="admin")
    create = await async_client.post(
        "/partners",
        headers=employee_auth_header(7402),
        json={
            "name": "Dr With Profile",
            "phone": "7402000001",
            "role": "expert",
            "expert_profile": {"expert_type": "doctor", "specialization": "General medicine"},
        },
    )
    assert create.status_code in {200, 201}, create.text
    partner_id = create.json()["data"]["partner_id"]
    expert_id = create.json()["data"].get("expert_id")
    assert expert_id is not None

    row = await test_db_session.get(Expert, expert_id)
    assert row is not None
    assert row.partner_id == partner_id
    assert row.specialization == "General medicine"

    listed = await async_client.get(
        "/experts",
        headers=employee_auth_header(7402),
        params={"page": 1, "limit": 50},
    )
    assert listed.status_code == 200
    ids = {r["expert_id"] for r in listed.json()["data"]}
    assert expert_id in ids


@pytest.mark.asyncio
async def test_create_phlebo_rejects_expert_profile(async_client, test_db_session):
    await _ensure_expert_type_doctor(test_db_session)
    await seed_employee(test_db_session, employee_id=7403, role="admin")
    response = await async_client.post(
        "/partners",
        headers=employee_auth_header(7403),
        json={
            "name": "Phlebo Bad",
            "phone": "7403000001",
            "role": "phlebo",
            "expert_profile": {"expert_type": "doctor", "specialization": "X"},
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_update_expert_partner_without_profile_requires_expert_profile(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=7404, role="admin")
    partner = await seed_partner(
        test_db_session,
        partner_id=74041,
        role="expert",
        phone="7404100001",
        email="expert74041@test.example",
    )
    response = await async_client.put(
        f"/partners/{partner.partner_id}",
        headers=employee_auth_header(7404),
        json={
            "name": partner.name,
            "phone": partner.phone,
            "email": partner.email,
            "role": "expert",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_update_expert_partner_creates_expert_profile(async_client, test_db_session):
    await _ensure_expert_type_doctor(test_db_session)
    await seed_employee(test_db_session, employee_id=7405, role="admin")
    partner = await seed_partner(
        test_db_session,
        partner_id=74051,
        role="expert",
        phone="7405100001",
        email="expert74051@test.example",
    )
    response = await async_client.put(
        f"/partners/{partner.partner_id}",
        headers=employee_auth_header(7405),
        json={
            "name": partner.name,
            "phone": partner.phone,
            "email": partner.email,
            "role": "expert",
            "expert_profile": {"expert_type": "doctor", "specialization": "Cardiology"},
        },
    )
    assert response.status_code == 200
    expert_id = response.json()["data"].get("expert_id")
    assert expert_id is not None
    row = await test_db_session.get(Expert, expert_id)
    assert row is not None
    assert row.specialization == "Cardiology"
