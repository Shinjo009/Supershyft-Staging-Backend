"""Integration tests for expert portal camp consultation routes."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest

from core.config import settings
from modules.auth.service import AuthService
from modules.engagements.enums import ConsultationMode
from modules.engagements.models import Engagement, EngagementParticipant, OnboardingAssistantAssignment
from modules.experts.consultations import empty_consent
from modules.experts.models import ConsultationBooking, Expert
from modules.organizations.models import Organization
from modules.users.models import User
from tests.helpers.auth import partner_auth_header, seed_partner


async def _seed_camp_setup(
    test_db_session,
    *,
    engagement_id: int,
    expert_partner_id: int,
    participant_user_id: int,
    participant_id: int,
    nutritionist_consultation_id: int,
    doctor_consultation_id: int,
    assign_expert_as_oa: bool = True,
    expert_type: str = "nutritionist",
) -> Expert:
    test_db_session.add(
        Organization(
            organization_id=8860,
            name="Camp Org",
            organization_type="corporate",
            status="active",
        )
    )
    test_db_session.add(
        User(
            user_id=participant_user_id,
            age=30,
            phone="886000000002",
            email="participant.camp@example.com",
            first_name="Camp",
            last_name="Patient",
            status="active",
        )
    )
    await test_db_session.flush()
    await seed_partner(
        test_db_session,
        partner_id=expert_partner_id,
        role="expert",
        name="Nutri Expert",
        phone="886000000001",
        email="expert.camp@example.com",
        commit=False,
    )
    expert = Expert(
        partner_id=expert_partner_id,
        expert_type=expert_type,
        specialization="Nutrition",
        status="active",
    )
    test_db_session.add(expert)
    await test_db_session.flush()

    past_slot = datetime.now() - timedelta(hours=2)
    test_db_session.add(
        Engagement(
            engagement_id=engagement_id,
            engagement_name="Camp Consultation",
            engagement_code=f"CAMP{engagement_id}",
            engagement_type=1,
            organization_id=8860,
            camp_no=886001,
            consultations={"doctor": True, "nutritionist": True},
            consultation_mode=ConsultationMode.offline,
            assessment_package_id=1,
            diagnostic_package_id=1,
            city="BLR",
            slot_duration=20,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=1),
            status="running",
        )
    )
    await test_db_session.flush()
    if assign_expert_as_oa:
        test_db_session.add(
            OnboardingAssistantAssignment(
                onboarding_assistant_id=886001,
                partner_id=expert_partner_id,
                engagement_id=engagement_id,
            )
        )
    test_db_session.add(
        EngagementParticipant(
            engagement_participant_id=participant_id,
            engagement_id=engagement_id,
            user_id=participant_user_id,
            booked_by_user_id=participant_user_id,
            consultation_booking_ids=[nutritionist_consultation_id, doctor_consultation_id],
        )
    )
    await test_db_session.flush()
    test_db_session.add_all(
        [
            ConsultationBooking(
                consultation_id=nutritionist_consultation_id,
                engagement_participant_id=participant_id,
                expert_type="nutritionist",
                want=True,
                consultation_date=past_slot.date(),
                consultation_slot=past_slot.strftime("%H:%M"),
                consultation_cabin="C1",
                done=False,
                consent={"bio_ai": True, "blood_report": False, "questionnaire": True},
            ),
            ConsultationBooking(
                consultation_id=doctor_consultation_id,
                engagement_participant_id=participant_id,
                expert_type="doctor",
                want=True,
                consultation_date=past_slot.date(),
                consultation_slot=past_slot.strftime("%H:%M"),
                consultation_cabin="C2",
                done=False,
            ),
        ]
    )
    await test_db_session.commit()
    return expert


async def _seed_unrequested_participant(
    test_db_session,
    *,
    engagement_id: int,
    participant_id: int,
    user_id: int,
    phone: str = "886000000099",
) -> None:
    test_db_session.add(
        User(
            user_id=user_id,
            age=29,
            phone=phone,
            email=f"unrequested.{user_id}@example.com",
            first_name="Pending",
            last_name="Participant",
            status="active",
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        EngagementParticipant(
            engagement_participant_id=participant_id,
            engagement_id=engagement_id,
            user_id=user_id,
            booked_by_user_id=user_id,
            consultation_booking_ids=[],
        )
    )
    await test_db_session.commit()


def _direct_request_url(engagement_id: int, engagement_participant_id: int) -> str:
    return (
        f"/experts/portal/camp-consultations/engagements/{engagement_id}/participants/"
        f"{engagement_participant_id}/request-consultation"
    )


def _send_otp_url(engagement_id: int, engagement_participant_id: int) -> str:
    return (
        f"/experts/portal/camp-consultations/engagements/{engagement_id}/participants/"
        f"{engagement_participant_id}/request-consultation/send-otp"
    )


def _verify_otp_url(engagement_id: int, engagement_participant_id: int) -> str:
    return (
        f"/experts/portal/camp-consultations/engagements/{engagement_id}/participants/"
        f"{engagement_participant_id}/request-consultation/verify-otp"
    )


def _send_consent_otp_url(engagement_id: int, engagement_participant_id: int) -> str:
    return (
        f"/experts/portal/camp-consultations/engagements/{engagement_id}/participants/"
        f"{engagement_participant_id}/update-consent/send-otp"
    )


def _verify_consent_otp_url(engagement_id: int, engagement_participant_id: int) -> str:
    return (
        f"/experts/portal/camp-consultations/engagements/{engagement_id}/participants/"
        f"{engagement_participant_id}/update-consent/verify-otp"
    )


_CONSENT_BODY = {
    "consent": {"bio_ai": True, "blood_report": False, "questionnaire": True},
}


@pytest.mark.asyncio
async def test_camp_consultation_engagements_only_for_assigned_offline(async_client, test_db_session):
    engagement_id = 88601
    expert_partner_id = 88601
    other_engagement_id = 88602

    await _seed_camp_setup(
        test_db_session,
        engagement_id=engagement_id,
        expert_partner_id=expert_partner_id,
        participant_user_id=88611,
        participant_id=88611,
        nutritionist_consultation_id=886101,
        doctor_consultation_id=886102,
        assign_expert_as_oa=True,
    )

    test_db_session.add(
        Engagement(
            engagement_id=other_engagement_id,
            engagement_name="Other Offline Camp",
            engagement_code="CAMP88602",
            engagement_type=1,
            organization_id=8860,
            camp_no=886002,
            consultations={"nutritionist": True},
            consultation_mode=ConsultationMode.offline,
            assessment_package_id=1,
            diagnostic_package_id=1,
            city="BLR",
            slot_duration=20,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=1),
            status="running",
        )
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/experts/portal/camp-consultations/engagements",
        headers=partner_auth_header(expert_partner_id),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    engagement_ids = {item["engagement_id"] for item in data}
    assert engagement_id in engagement_ids
    assert other_engagement_id not in engagement_ids
    assigned = next(item for item in data if item["engagement_id"] == engagement_id)
    assert assigned["consultation_pending_count"] == 1


@pytest.mark.asyncio
async def test_camp_consultation_participants_filter_by_expert_type_and_mask_pii(
    async_client, test_db_session
):
    engagement_id = 88603
    expert_partner_id = 88603

    await _seed_camp_setup(
        test_db_session,
        engagement_id=engagement_id,
        expert_partner_id=expert_partner_id,
        participant_user_id=88613,
        participant_id=88613,
        nutritionist_consultation_id=886301,
        doctor_consultation_id=886302,
    )
    test_db_session.add(
        User(
            user_id=88617,
            age=28,
            phone="886000000017",
            email="not.requested@example.com",
            first_name="No",
            last_name="Request",
            status="active",
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        EngagementParticipant(
            engagement_participant_id=88617,
            engagement_id=engagement_id,
            user_id=88617,
            booked_by_user_id=88617,
            consultation_booking_ids=[],
        )
    )
    await test_db_session.commit()

    response = await async_client.get(
        f"/experts/portal/camp-consultations/engagements/{engagement_id}/participants",
        headers=partner_auth_header(expert_partner_id),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 2
    requested_rows = [row for row in data if row["requested"]]
    assert len(requested_rows) == 1
    item = requested_rows[0]
    assert item["expert_type"] == "nutritionist"
    assert item["consultation_id"] == 886301
    assert item["engagement_participant_id"] == 88613
    assert item["phone"] == "********0002"
    assert item["email"].endswith("@example.com")
    assert "*" in item["email"]
    assert item["cabin"] == "C1"
    not_requested = next(row for row in data if row["engagement_participant_id"] == 88617)
    assert not_requested["requested"] is False
    assert not_requested["consultation_id"] is None


@pytest.mark.asyncio
async def test_camp_consultation_manage_without_expert_id(async_client, test_db_session):
    engagement_id = 88604
    expert_partner_id = 88604
    consultation_id = 886401

    await _seed_camp_setup(
        test_db_session,
        engagement_id=engagement_id,
        expert_partner_id=expert_partner_id,
        participant_user_id=88614,
        participant_id=88614,
        nutritionist_consultation_id=consultation_id,
        doctor_consultation_id=886402,
    )

    expert_headers = partner_auth_header(expert_partner_id)

    detail = await async_client.get(
        f"/experts/portal/consultations/{consultation_id}",
        headers=expert_headers,
    )
    assert detail.status_code == 200
    body = detail.json()["data"]
    assert body["consultation_id"] == consultation_id
    assert body["cabin"] == "C1"
    assert body["phone"] == "********0002"
    assert "*" in body["email"]
    assert body["within_engagement_window"] is True

    patch = await async_client.patch(
        f"/experts/portal/consultations/{consultation_id}",
        headers=expert_headers,
        json={"consultation_summary": "Camp consult complete"},
    )
    assert patch.status_code == 200
    assert patch.json()["data"]["consultation_summary"] == "Camp consult complete"

    done = await async_client.post(
        f"/experts/portal/consultations/{consultation_id}/done",
        headers=expert_headers,
    )
    assert done.status_code == 200
    assert done.json()["data"]["done"] is True


@pytest.mark.asyncio
async def test_camp_consultation_forbidden_without_oa_assignment(async_client, test_db_session):
    engagement_id = 88605
    expert_partner_id = 88605
    consultation_id = 886501

    await _seed_camp_setup(
        test_db_session,
        engagement_id=engagement_id,
        expert_partner_id=expert_partner_id,
        participant_user_id=88615,
        participant_id=88615,
        nutritionist_consultation_id=consultation_id,
        doctor_consultation_id=886502,
        assign_expert_as_oa=False,
    )

    expert_headers = partner_auth_header(expert_partner_id)

    response = await async_client.get(
        f"/experts/portal/camp-consultations/engagements/{engagement_id}/participants",
        headers=expert_headers,
    )
    assert response.status_code == 403

    manage = await async_client.get(
        f"/experts/portal/consultations/{consultation_id}",
        headers=expert_headers,
    )
    assert manage.status_code == 403


@pytest.mark.asyncio
async def test_camp_consultation_manage_rejects_wrong_expert_type(async_client, test_db_session):
    engagement_id = 88606
    expert_partner_id = 88606
    doctor_consultation_id = 886602

    await _seed_camp_setup(
        test_db_session,
        engagement_id=engagement_id,
        expert_partner_id=expert_partner_id,
        participant_user_id=88616,
        participant_id=88616,
        nutritionist_consultation_id=886601,
        doctor_consultation_id=doctor_consultation_id,
    )

    response = await async_client.get(
        f"/experts/portal/consultations/{doctor_consultation_id}",
        headers=partner_auth_header(expert_partner_id),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_camp_direct_request_without_otp_happy_path(async_client, test_db_session):
    engagement_id = 88616
    expert_partner_id = 88616
    participant_id = 886161

    await _seed_camp_setup(
        test_db_session,
        engagement_id=engagement_id,
        expert_partner_id=expert_partner_id,
        participant_user_id=886160,
        participant_id=886160,
        nutritionist_consultation_id=8861601,
        doctor_consultation_id=8861602,
    )
    await _seed_unrequested_participant(
        test_db_session,
        engagement_id=engagement_id,
        participant_id=participant_id,
        user_id=886161,
    )

    expert_headers = partner_auth_header(expert_partner_id)
    response = await async_client.post(
        _direct_request_url(engagement_id, participant_id),
        headers=expert_headers,
        json={},
    )
    assert response.status_code == 200
    row = response.json()["data"]
    assert row["requested"] is True
    assert row["engagement_participant_id"] == participant_id
    assert row["consultation_id"] is not None
    assert row["consent"] == empty_consent()


@pytest.mark.asyncio
async def test_camp_direct_request_already_requested(async_client, test_db_session):
    engagement_id = 88617
    expert_partner_id = 88617
    participant_id = 88617

    await _seed_camp_setup(
        test_db_session,
        engagement_id=engagement_id,
        expert_partner_id=expert_partner_id,
        participant_user_id=participant_id,
        participant_id=participant_id,
        nutritionist_consultation_id=8861701,
        doctor_consultation_id=8861702,
    )

    response = await async_client.post(
        _direct_request_url(engagement_id, participant_id),
        headers=partner_auth_header(expert_partner_id),
        json={},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_camp_direct_request_forbidden_without_oa(async_client, test_db_session):
    engagement_id = 88618
    expert_partner_id = 88618
    participant_id = 886181

    await _seed_camp_setup(
        test_db_session,
        engagement_id=engagement_id,
        expert_partner_id=expert_partner_id,
        participant_user_id=886180,
        participant_id=886180,
        nutritionist_consultation_id=8861801,
        doctor_consultation_id=8861802,
        assign_expert_as_oa=False,
    )
    await _seed_unrequested_participant(
        test_db_session,
        engagement_id=engagement_id,
        participant_id=participant_id,
        user_id=886181,
    )

    response = await async_client.post(
        _direct_request_url(engagement_id, participant_id),
        headers=partner_auth_header(expert_partner_id),
        json={},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_camp_request_consultation_otp_happy_path(
    async_client, test_db_session, monkeypatch
):
    engagement_id = 88607
    expert_partner_id = 88607
    participant_id = 88671
    participant_user_id = 88671

    await _seed_camp_setup(
        test_db_session,
        engagement_id=engagement_id,
        expert_partner_id=expert_partner_id,
        participant_user_id=88670,
        participant_id=88670,
        nutritionist_consultation_id=886701,
        doctor_consultation_id=886702,
    )
    await _seed_unrequested_participant(
        test_db_session,
        engagement_id=engagement_id,
        participant_id=participant_id,
        user_id=participant_user_id,
    )

    captured: dict[str, Any] = {}

    async def _capture_delivery(self, db, *, delivery):
        captured["otp"] = delivery.otp

    monkeypatch.setattr(AuthService, "deliver_otp_via_notifications", _capture_delivery)

    expert_headers = partner_auth_header(expert_partner_id)
    send = await async_client.post(
        _send_otp_url(engagement_id, participant_id),
        headers=expert_headers,
        json=_CONSENT_BODY,
    )
    assert send.status_code == 200
    send_data = send.json()["data"]
    assert send_data["session_id"] is not None
    assert "masked_phone" in send_data
    assert captured.get("otp")

    verify = await async_client.post(
        _verify_otp_url(engagement_id, participant_id),
        headers=expert_headers,
        json={"session_id": send_data["session_id"], "otp": captured["otp"]},
    )
    assert verify.status_code == 200
    row = verify.json()["data"]
    assert row["requested"] is True
    assert row["engagement_participant_id"] == participant_id
    assert row["consultation_id"] is not None
    assert row["consent"] == _CONSENT_BODY["consent"]

    listed = await async_client.get(
        f"/experts/portal/camp-consultations/engagements/{engagement_id}/participants",
        headers=expert_headers,
    )
    assert listed.status_code == 200
    updated = next(
        item
        for item in listed.json()["data"]
        if item["engagement_participant_id"] == participant_id
    )
    assert updated["requested"] is True
    assert updated["consent"] == _CONSENT_BODY["consent"]


@pytest.mark.asyncio
async def test_camp_request_consultation_send_otp_forbidden_without_oa(
    async_client, test_db_session, monkeypatch
):
    engagement_id = 88608
    expert_partner_id = 88608
    participant_id = 88681

    await _seed_camp_setup(
        test_db_session,
        engagement_id=engagement_id,
        expert_partner_id=expert_partner_id,
        participant_user_id=88680,
        participant_id=88680,
        nutritionist_consultation_id=886801,
        doctor_consultation_id=886802,
        assign_expert_as_oa=False,
    )
    await _seed_unrequested_participant(
        test_db_session,
        engagement_id=engagement_id,
        participant_id=participant_id,
        user_id=88681,
    )

    async def _noop_delivery(self, db, *, delivery):
        return None

    monkeypatch.setattr(AuthService, "deliver_otp_via_notifications", _noop_delivery)

    response = await async_client.post(
        _send_otp_url(engagement_id, participant_id),
        headers=partner_auth_header(expert_partner_id),
        json=_CONSENT_BODY,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_camp_request_consultation_send_otp_already_requested(
    async_client, test_db_session, monkeypatch
):
    engagement_id = 88609
    expert_partner_id = 88609
    participant_id = 88690

    await _seed_camp_setup(
        test_db_session,
        engagement_id=engagement_id,
        expert_partner_id=expert_partner_id,
        participant_user_id=participant_id,
        participant_id=participant_id,
        nutritionist_consultation_id=886901,
        doctor_consultation_id=886902,
    )

    async def _noop_delivery(self, db, *, delivery):
        return None

    monkeypatch.setattr(AuthService, "deliver_otp_via_notifications", _noop_delivery)

    response = await async_client.post(
        _send_otp_url(engagement_id, participant_id),
        headers=partner_auth_header(expert_partner_id),
        json=_CONSENT_BODY,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_camp_request_consultation_verify_invalid_otp(
    async_client, test_db_session, monkeypatch
):
    engagement_id = 88610
    expert_partner_id = 88610
    participant_id = 88701

    await _seed_camp_setup(
        test_db_session,
        engagement_id=engagement_id,
        expert_partner_id=expert_partner_id,
        participant_user_id=88700,
        participant_id=88700,
        nutritionist_consultation_id=887001,
        doctor_consultation_id=887002,
    )
    await _seed_unrequested_participant(
        test_db_session,
        engagement_id=engagement_id,
        participant_id=participant_id,
        user_id=88701,
    )

    async def _noop_delivery(self, db, *, delivery):
        return None

    monkeypatch.setattr(AuthService, "deliver_otp_via_notifications", _noop_delivery)
    monkeypatch.setattr(settings, "ALLOW_BYPASS_OTP", False, raising=False)

    expert_headers = partner_auth_header(expert_partner_id)
    send = await async_client.post(
        _send_otp_url(engagement_id, participant_id),
        headers=expert_headers,
        json=_CONSENT_BODY,
    )
    assert send.status_code == 200
    session_id = send.json()["data"]["session_id"]

    verify = await async_client.post(
        _verify_otp_url(engagement_id, participant_id),
        headers=expert_headers,
        json={"session_id": session_id, "otp": "000000"},
    )
    assert verify.status_code == 401


@pytest.mark.asyncio
async def test_camp_update_consent_otp_happy_path(async_client, test_db_session, monkeypatch):
    engagement_id = 88611
    expert_partner_id = 88611
    participant_id = 88611
    nutritionist_consultation_id = 886111

    await _seed_camp_setup(
        test_db_session,
        engagement_id=engagement_id,
        expert_partner_id=expert_partner_id,
        participant_user_id=participant_id,
        participant_id=participant_id,
        nutritionist_consultation_id=nutritionist_consultation_id,
        doctor_consultation_id=886112,
    )
    booking = await test_db_session.get(ConsultationBooking, nutritionist_consultation_id)
    booking.consent = empty_consent()
    await test_db_session.commit()

    captured: dict[str, Any] = {}

    async def _capture_delivery(self, db, *, delivery):
        captured["otp"] = delivery.otp

    monkeypatch.setattr(AuthService, "deliver_otp_via_notifications", _capture_delivery)

    expert_headers = partner_auth_header(expert_partner_id)
    send = await async_client.post(
        _send_consent_otp_url(engagement_id, participant_id),
        headers=expert_headers,
        json=_CONSENT_BODY,
    )
    assert send.status_code == 200
    send_data = send.json()["data"]
    assert captured.get("otp")

    verify = await async_client.post(
        _verify_consent_otp_url(engagement_id, participant_id),
        headers=expert_headers,
        json={"session_id": send_data["session_id"], "otp": captured["otp"]},
    )
    assert verify.status_code == 200
    row = verify.json()["data"]
    assert row["requested"] is True
    assert row["consent"] == _CONSENT_BODY["consent"]
    assert row["consultation_id"] == nutritionist_consultation_id


@pytest.mark.asyncio
async def test_camp_update_consent_send_otp_not_requested_yet(
    async_client, test_db_session, monkeypatch
):
    engagement_id = 88612
    expert_partner_id = 88612
    participant_id = 886122

    await _seed_camp_setup(
        test_db_session,
        engagement_id=engagement_id,
        expert_partner_id=expert_partner_id,
        participant_user_id=886120,
        participant_id=886120,
        nutritionist_consultation_id=886121,
        doctor_consultation_id=886122,
    )
    await _seed_unrequested_participant(
        test_db_session,
        engagement_id=engagement_id,
        participant_id=participant_id,
        user_id=886122,
    )

    async def _noop_delivery(self, db, *, delivery):
        return None

    monkeypatch.setattr(AuthService, "deliver_otp_via_notifications", _noop_delivery)

    response = await async_client.post(
        _send_consent_otp_url(engagement_id, participant_id),
        headers=partner_auth_header(expert_partner_id),
        json=_CONSENT_BODY,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_camp_update_consent_send_otp_already_complete(
    async_client, test_db_session, monkeypatch
):
    engagement_id = 88613
    expert_partner_id = 88613
    participant_id = 88613

    await _seed_camp_setup(
        test_db_session,
        engagement_id=engagement_id,
        expert_partner_id=expert_partner_id,
        participant_user_id=participant_id,
        participant_id=participant_id,
        nutritionist_consultation_id=886131,
        doctor_consultation_id=886132,
    )
    booking = await test_db_session.get(ConsultationBooking, 886131)
    booking.consent = {
        "bio_ai": True,
        "blood_report": True,
        "questionnaire": True,
    }
    await test_db_session.commit()

    async def _noop_delivery(self, db, *, delivery):
        return None

    monkeypatch.setattr(AuthService, "deliver_otp_via_notifications", _noop_delivery)

    response = await async_client.post(
        _send_consent_otp_url(engagement_id, participant_id),
        headers=partner_auth_header(expert_partner_id),
        json=_CONSENT_BODY,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_camp_update_consent_send_otp_forbidden_without_oa(
    async_client, test_db_session, monkeypatch
):
    engagement_id = 88614
    expert_partner_id = 88614
    participant_id = 88614

    await _seed_camp_setup(
        test_db_session,
        engagement_id=engagement_id,
        expert_partner_id=expert_partner_id,
        participant_user_id=participant_id,
        participant_id=participant_id,
        nutritionist_consultation_id=886141,
        doctor_consultation_id=886142,
        assign_expert_as_oa=False,
    )

    async def _noop_delivery(self, db, *, delivery):
        return None

    monkeypatch.setattr(AuthService, "deliver_otp_via_notifications", _noop_delivery)

    response = await async_client.post(
        _send_consent_otp_url(engagement_id, participant_id),
        headers=partner_auth_header(expert_partner_id),
        json=_CONSENT_BODY,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_camp_update_consent_verify_invalid_otp(
    async_client, test_db_session, monkeypatch
):
    engagement_id = 88615
    expert_partner_id = 88615
    participant_id = 88615
    nutritionist_consultation_id = 886151

    await _seed_camp_setup(
        test_db_session,
        engagement_id=engagement_id,
        expert_partner_id=expert_partner_id,
        participant_user_id=participant_id,
        participant_id=participant_id,
        nutritionist_consultation_id=nutritionist_consultation_id,
        doctor_consultation_id=886152,
    )
    booking = await test_db_session.get(ConsultationBooking, nutritionist_consultation_id)
    booking.consent = empty_consent()
    await test_db_session.commit()

    async def _noop_delivery(self, db, *, delivery):
        return None

    monkeypatch.setattr(AuthService, "deliver_otp_via_notifications", _noop_delivery)
    monkeypatch.setattr(settings, "ALLOW_BYPASS_OTP", False, raising=False)

    expert_headers = partner_auth_header(expert_partner_id)
    send = await async_client.post(
        _send_consent_otp_url(engagement_id, participant_id),
        headers=expert_headers,
        json=_CONSENT_BODY,
    )
    assert send.status_code == 200
    session_id = send.json()["data"]["session_id"]

    verify = await async_client.post(
        _verify_consent_otp_url(engagement_id, participant_id),
        headers=expert_headers,
        json={"session_id": session_id, "otp": "000000"},
    )
    assert verify.status_code == 401
