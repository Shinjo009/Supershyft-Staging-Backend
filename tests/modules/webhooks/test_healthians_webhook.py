"""Tests for POST /webhooks/healthians."""

from __future__ import annotations

from datetime import date, time

import pytest
from sqlalchemy import text

from modules.engagements.models import Engagement, EngagementParticipant
from modules.users.models import User


def _sample_payload(
    *,
    booking_id: str = "1387716654555",
    event_type: str = "status_updated",
    booking_status: str = "BS005",
    ref_booking_id: str | None = None,
    sample_collection_date: str | None = "2026-05-01",
    start_time: str | None = "10:00 AM",
    end_time: str | None = "11:00 AM",
) -> dict:
    data: dict = {
        "booking_status": booking_status,
        "customer_status": booking_status,
    }
    if sample_collection_date is not None:
        data["sample_collection_date"] = sample_collection_date
    if start_time is not None:
        data["start_time"] = start_time
    if end_time is not None:
        data["end_time"] = end_time
    if ref_booking_id is not None:
        data["ref_booking_id"] = ref_booking_id
    return {
        "type": event_type,
        "booking_id": booking_id,
        "data": data,
    }


async def _seed_booking_confirmation_services(test_db_session) -> None:
    for service_key, channel, webhook_path in (
        (
            "booking-confirmation-whatsapp",
            "whatsapp",
            "/booking-confirmation-whatsapp-v1",
        ),
        (
            "booking-confirmation-email",
            "email",
            "/booking-confirmation-email-v1",
        ),
    ):
        await test_db_session.execute(
            text(
                """
                INSERT INTO notification_services (
                    service_key, display_name, channel, webhook_path, is_active,
                    require_blood_report_url, require_bio_ai_report_url,
                    require_participant_detail, require_otp, require_session_details,
                    require_external_link
                ) VALUES (
                    :service_key, :display_name, :channel, :webhook_path, true,
                    false, false, false, false, true, false
                )
                ON CONFLICT (service_key) DO UPDATE SET
                    is_active = true,
                    require_session_details = true,
                    webhook_path = EXCLUDED.webhook_path
                """
            ),
            {
                "service_key": service_key,
                "display_name": service_key,
                "channel": channel,
                "webhook_path": webhook_path,
            },
        )
    await test_db_session.commit()


async def _seed_diagnostic_package(test_db_session, *, diagnostic_package_id: int = 1):
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, reference_id, package_name, diagnostic_provider, status, bookings_count) "
            "VALUES (:did, :ref, :pname, 'Healthians', 'active', 0) ON CONFLICT (diagnostic_package_id) DO NOTHING"
        ),
        {"did": diagnostic_package_id, "ref": f"REF{diagnostic_package_id}", "pname": "Diag"},
    )
    await test_db_session.commit()


async def _seed_engagement(test_db_session, *, engagement_id: int, engagement_code: str):
    await _seed_diagnostic_package(test_db_session)
    test_db_session.add(
        Engagement(
            engagement_id=engagement_id,
            engagement_name="Camp",
            engagement_code=engagement_code,
            engagement_type=None,
            assessment_package_id=1,
            diagnostic_package_id=1,
            city="BLR",
            slot_duration=20,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            status="active",
        )
    )
    await test_db_session.commit()


async def _seed_user(test_db_session, *, user_id: int):
    test_db_session.add(
        User(
            user_id=user_id,
            age=30,
            phone=f"{user_id}000000000",
            status="active",
        )
    )
    await test_db_session.flush()


async def _seed_participant(
    test_db_session,
    *,
    engagement_participant_id: int,
    engagement_id: int,
    user_id: int,
    booking_id: str | None = None,
):
    await _seed_user(test_db_session, user_id=user_id)
    test_db_session.add(
        EngagementParticipant(
            engagement_participant_id=engagement_participant_id,
            engagement_id=engagement_id,
            user_id=user_id,
            engagement_date=date(2026, 5, 1),
            slot_start_time=time(10, 0),
            booking_id=booking_id,
        )
    )
    await test_db_session.commit()


def _fake_httpx_client(*, succeed: bool = True):
    class _FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            if not succeed:
                raise RuntimeError("webhook failed")

        def json(self):
            return {"message": "ok"}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json=None):
            return _FakeResponse()

    return _FakeClient


@pytest.mark.asyncio
async def test_receive_creates_inbound_sync_log(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr(
        "modules.webhooks.sender.service.settings.HEALTHIANS_WEBHOOK_FORWARD_URL",
        "",
    )

    payload = _sample_payload()
    response = await async_client.post("/webhooks/healthians", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()["data"]
    assert body["received"] is True
    assert body["sync_log_id"] is not None
    assert body["forwards"] == []

    result = await test_db_session.execute(
        text(
            "SELECT provider, engagement_id, user_id, api_endpoint_url, request_payload, "
            "response_payload, status, error_message "
            "FROM integration_sync_logs WHERE sync_log_id = :sync_log_id"
        ),
        {"sync_log_id": body["sync_log_id"]},
    )
    row = result.mappings().one()
    assert row["provider"] == "healthians"
    assert row["engagement_id"] is None
    assert row["user_id"] is None
    assert row["api_endpoint_url"] == "/webhooks/healthians"
    assert row["request_payload"]["booking_id"] == payload["booking_id"]
    assert row["status"] == "success"
    assert row["response_payload"]["received"] is True
    assert row["error_message"] is None


@pytest.mark.asyncio
async def test_receive_resolves_engagement_and_user(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr(
        "modules.webhooks.sender.service.settings.HEALTHIANS_WEBHOOK_FORWARD_URL",
        "",
    )

    await _seed_engagement(test_db_session, engagement_id=9701, engagement_code="ENG9701")
    await _seed_participant(
        test_db_session,
        engagement_participant_id=97001,
        engagement_id=9701,
        user_id=9701,
        booking_id="1387716654555",
    )

    response = await async_client.post(
        "/webhooks/healthians",
        json=_sample_payload(booking_id="1387716654555"),
    )
    assert response.status_code == 200, response.text
    sync_log_id = response.json()["data"]["sync_log_id"]

    result = await test_db_session.execute(
        text(
            "SELECT engagement_id, user_id "
            "FROM integration_sync_logs WHERE sync_log_id = :sync_log_id"
        ),
        {"sync_log_id": sync_log_id},
    )
    row = result.mappings().one()
    assert row["engagement_id"] == 9701
    assert row["user_id"] == 9701


@pytest.mark.asyncio
async def test_receive_unknown_booking_id(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr(
        "modules.webhooks.sender.service.settings.HEALTHIANS_WEBHOOK_FORWARD_URL",
        "",
    )

    response = await async_client.post(
        "/webhooks/healthians",
        json=_sample_payload(booking_id="unknown-booking-id"),
    )
    assert response.status_code == 200, response.text

    sync_log_id = response.json()["data"]["sync_log_id"]
    result = await test_db_session.execute(
        text(
            "SELECT engagement_id, user_id, status "
            "FROM integration_sync_logs WHERE sync_log_id = :sync_log_id"
        ),
        {"sync_log_id": sync_log_id},
    )
    row = result.mappings().one()
    assert row["engagement_id"] is None
    assert row["user_id"] is None
    assert row["status"] == "success"


@pytest.mark.asyncio
async def test_ref_booking_id_fallback(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr(
        "modules.webhooks.sender.service.settings.HEALTHIANS_WEBHOOK_FORWARD_URL",
        "",
    )

    await _seed_engagement(test_db_session, engagement_id=9702, engagement_code="ENG9702")
    await _seed_participant(
        test_db_session,
        engagement_participant_id=97002,
        engagement_id=9702,
        user_id=9702,
        booking_id="22494618",
    )

    response = await async_client.post(
        "/webhooks/healthians",
        json=_sample_payload(booking_id="224949781", ref_booking_id="22494618"),
    )
    assert response.status_code == 200, response.text
    sync_log_id = response.json()["data"]["sync_log_id"]

    result = await test_db_session.execute(
        text(
            "SELECT engagement_id, user_id "
            "FROM integration_sync_logs WHERE sync_log_id = :sync_log_id"
        ),
        {"sync_log_id": sync_log_id},
    )
    row = result.mappings().one()
    assert row["engagement_id"] == 9702
    assert row["user_id"] == 9702


@pytest.mark.asyncio
async def test_forward_creates_outbound_sync_logs(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr(
        "modules.webhooks.sender.service.settings.HEALTHIANS_WEBHOOK_FORWARD_URL",
        "https://forward-one.test/hook,https://forward-two.test/hook",
    )
    monkeypatch.setattr(
        "modules.webhooks.sender.service.httpx.AsyncClient",
        _fake_httpx_client(succeed=True),
    )

    payload = _sample_payload(booking_id="forward-booking-1")
    response = await async_client.post("/webhooks/healthians", json=payload)
    assert response.status_code == 200, response.text

    data = response.json()["data"]
    assert len(data["forwards"]) == 2
    assert all(item["status"] == "success" for item in data["forwards"])

    result = await test_db_session.execute(
        text(
            "SELECT api_endpoint_url, request_payload, response_payload, status "
            "FROM integration_sync_logs "
            "WHERE provider = 'healthians' "
            "AND api_endpoint_url LIKE 'https://forward-%' "
            "ORDER BY sync_log_id ASC"
        )
    )
    rows = result.mappings().all()
    assert len(rows) == 2
    assert rows[0]["api_endpoint_url"] == "https://forward-one.test/hook"
    assert rows[1]["api_endpoint_url"] == "https://forward-two.test/hook"
    assert rows[0]["request_payload"]["booking_id"] == payload["booking_id"]
    assert rows[0]["status"] == "success"
    assert rows[0]["response_payload"] == {"message": "ok"}


@pytest.mark.asyncio
async def test_forward_failure_logged(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr(
        "modules.webhooks.sender.service.settings.HEALTHIANS_WEBHOOK_FORWARD_URL",
        "https://forward-fail.test/hook",
    )
    monkeypatch.setattr(
        "modules.webhooks.sender.service.httpx.AsyncClient",
        _fake_httpx_client(succeed=False),
    )

    response = await async_client.post(
        "/webhooks/healthians",
        json=_sample_payload(booking_id="forward-fail-booking"),
    )
    assert response.status_code == 200, response.text

    data = response.json()["data"]
    assert data["received"] is True
    assert data["forwards"][0]["status"] == "failed"
    assert "webhook failed" in data["forwards"][0]["error"]

    inbound = await test_db_session.execute(
        text(
            "SELECT status FROM integration_sync_logs "
            "WHERE api_endpoint_url = '/webhooks/healthians' "
            "ORDER BY sync_log_id DESC LIMIT 1"
        )
    )
    assert inbound.mappings().one()["status"] == "success"

    outbound = await test_db_session.execute(
        text(
            "SELECT status, error_message, response_payload "
            "FROM integration_sync_logs "
            "WHERE api_endpoint_url = 'https://forward-fail.test/hook' "
            "ORDER BY sync_log_id DESC LIMIT 1"
        )
    )
    row = outbound.mappings().one()
    assert row["status"] == "failed"
    assert "webhook failed" in row["error_message"]
    assert row["response_payload"] is None


@pytest.mark.asyncio
async def test_bs005_dispatches_booking_confirmation_notifications(
    async_client, test_db_session, monkeypatch
):
    monkeypatch.setattr(
        "modules.webhooks.sender.service.settings.HEALTHIANS_WEBHOOK_FORWARD_URL",
        "",
    )
    await _seed_booking_confirmation_services(test_db_session)
    await _seed_engagement(test_db_session, engagement_id=9801, engagement_code="ENG9801")
    await _seed_participant(
        test_db_session,
        engagement_participant_id=98001,
        engagement_id=9801,
        user_id=9801,
        booking_id="1387716659801",
    )

    webhook_calls: list[dict] = []

    class _FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {"message": "ok", "accepted": True}

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

    monkeypatch.setattr("modules.notifications.service.httpx.AsyncClient", _FakeClient)

    response = await async_client.post(
        "/webhooks/healthians",
        json=_sample_payload(
            booking_id="1387716659801",
            sample_collection_date="2026-05-01",
            start_time="10:00 AM",
            end_time="11:00 AM",
        ),
    )
    assert response.status_code == 200, response.text

    body = response.json()["data"]
    assert "notifications" in body
    assert len(body["notifications"]) == 2
    by_key = {item["service_key"]: item for item in body["notifications"]}
    assert by_key["booking-confirmation-whatsapp"]["action"] == "dispatched"
    assert by_key["booking-confirmation-email"]["action"] == "dispatched"
    assert by_key["booking-confirmation-whatsapp"]["notification_id"] is not None
    assert by_key["booking-confirmation-email"]["notification_id"] is not None

    assert len(webhook_calls) == 2
    for call in webhook_calls:
        member = call["json"]["members"][0]
        assert member["session_details"]["date"] == "2026-05-01"
        assert member["session_details"]["slot"] == "10:00 AM to 11:00 AM"
        assert member["session_details"]["expert_type"] == "blood_collection"


@pytest.mark.asyncio
async def test_non_bs005_does_not_dispatch_booking_confirmation(
    async_client, test_db_session, monkeypatch
):
    monkeypatch.setattr(
        "modules.webhooks.sender.service.settings.HEALTHIANS_WEBHOOK_FORWARD_URL",
        "",
    )
    await _seed_booking_confirmation_services(test_db_session)
    await _seed_engagement(test_db_session, engagement_id=9802, engagement_code="ENG9802")
    await _seed_participant(
        test_db_session,
        engagement_participant_id=98002,
        engagement_id=9802,
        user_id=9802,
        booking_id="1387716659802",
    )

    dispatch_calls: list[dict] = []

    async def _fake_dispatch(self, db, *, payload, triggered_by_user_id=None):
        dispatch_calls.append(payload.model_dump(mode="json"))
        return {"notification_id": 1}

    monkeypatch.setattr(
        "modules.notifications.service.NotificationsService.dispatch",
        _fake_dispatch,
    )

    response = await async_client.post(
        "/webhooks/healthians",
        json=_sample_payload(
            booking_id="1387716659802",
            booking_status="BS007",
        ),
    )
    assert response.status_code == 200, response.text
    assert "notifications" not in response.json()["data"]
    assert dispatch_calls == []


@pytest.mark.asyncio
async def test_bs005_skips_when_already_sent(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr(
        "modules.webhooks.sender.service.settings.HEALTHIANS_WEBHOOK_FORWARD_URL",
        "",
    )
    await _seed_booking_confirmation_services(test_db_session)
    await _seed_engagement(test_db_session, engagement_id=9803, engagement_code="ENG9803")
    await _seed_participant(
        test_db_session,
        engagement_participant_id=98003,
        engagement_id=9803,
        user_id=9803,
        booking_id="1387716659803",
    )

    webhook_calls: list[dict] = []

    class _FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {"message": "ok", "accepted": True}

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

    monkeypatch.setattr("modules.notifications.service.httpx.AsyncClient", _FakeClient)

    payload = _sample_payload(booking_id="1387716659803")
    first = await async_client.post("/webhooks/healthians", json=payload)
    assert first.status_code == 200, first.text
    assert all(n["action"] == "dispatched" for n in first.json()["data"]["notifications"])
    assert len(webhook_calls) == 2

    second = await async_client.post("/webhooks/healthians", json=payload)
    assert second.status_code == 200, second.text
    assert all(n["action"] == "skipped" for n in second.json()["data"]["notifications"])
    assert all(
        n["reason"] in {"already sent", "already in flight"}
        for n in second.json()["data"]["notifications"]
    )
    assert len(webhook_calls) == 2
