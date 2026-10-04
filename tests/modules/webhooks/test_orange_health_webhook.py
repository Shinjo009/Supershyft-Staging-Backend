"""Tests for POST /webhooks/orange-health."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import pytest
from sqlalchemy import text

from core.config import settings
from tests.modules.engagements.test_blood_booking_id_validation import (
    _seed_engagement,
    _seed_participant,
)

_WEBHOOK_SECRET = "orange-health-webhook-test-secret"
_EVENT_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


def _configure_webhook_secret(monkeypatch, *, secret: str = _WEBHOOK_SECRET) -> None:
    monkeypatch.setattr(settings, "ORANGE_HEALTH_WEBHOOK_SECRET", secret)


def _sample_payload(
    *,
    event: str = "order.created",
    city_request_id: str = "BLR5383272",
    partner_reference_id: str = "patient_001",
) -> dict:
    return {
        "event": event,
        "contains": ["order", "request"],
        "payload": {
            "order": {
                "city_request_id": city_request_id,
                "id": 6139141,
                "partner_reference_id": partner_reference_id,
                "alnum_order_id": "OBLR6139141",
                "status_string": "requested",
            },
        },
    }


def _sign_body(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _webhook_headers(
    *,
    body: bytes,
    secret: str = _WEBHOOK_SECRET,
    signature: str | None = None,
    event_id: str = _EVENT_ID,
) -> dict[str, str]:
    sig = signature if signature is not None else _sign_body(body, secret)
    return {
        "x-oh-signature": sig,
        "x-oh-event-id": event_id,
        "content-type": "application/json",
    }


async def _post_orange_webhook(
    async_client,
    payload: dict,
    *,
    secret: str = _WEBHOOK_SECRET,
    signature: str | None = None,
    event_id: str = _EVENT_ID,
):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return await async_client.post(
        "/webhooks/orange-health",
        content=body,
        headers=_webhook_headers(body=body, secret=secret, signature=signature, event_id=event_id),
    )


@pytest.mark.asyncio
async def test_valid_signature_creates_integration_sync_log(async_client, test_db_session, monkeypatch):
    _configure_webhook_secret(monkeypatch)
    payload = _sample_payload()

    response = await _post_orange_webhook(async_client, payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["received"] is True
    assert data["event"] == "order.created"
    assert data["x_oh_event_id"] == _EVENT_ID
    sync_log_id = data["sync_log_id"]

    row = (
        await test_db_session.execute(
            text(
                "SELECT provider, status, api_endpoint_url, request_payload, engagement_id, user_id "
                "FROM integration_sync_logs WHERE sync_log_id = :sync_log_id"
            ),
            {"sync_log_id": sync_log_id},
        )
    ).mappings().one()

    assert row["provider"] == "orange_health"
    assert row["status"] in (2, "success")
    assert row["api_endpoint_url"] == "/webhooks/orange-health"
    req = row["request_payload"]
    assert req["event"] == "order.created"
    assert req["x_oh_event_id"] == _EVENT_ID
    assert req["body"]["event"] == "order.created"


@pytest.mark.asyncio
async def test_missing_signature_returns_401_without_log(async_client, test_db_session, monkeypatch):
    _configure_webhook_secret(monkeypatch)
    before = (
        await test_db_session.execute(
            text("SELECT COUNT(*) AS n FROM integration_sync_logs WHERE provider = 'orange_health'")
        )
    ).scalar_one()

    body = json.dumps(_sample_payload(), separators=(",", ":")).encode("utf-8")
    response = await async_client.post(
        "/webhooks/orange-health",
        content=body,
        headers={"x-oh-event-id": _EVENT_ID, "content-type": "application/json"},
    )
    assert response.status_code == 401, response.text
    assert response.json()["error_code"] == "AUTH_FAILED"

    after = (
        await test_db_session.execute(
            text("SELECT COUNT(*) AS n FROM integration_sync_logs WHERE provider = 'orange_health'")
        )
    ).scalar_one()
    assert after == before


@pytest.mark.asyncio
async def test_wrong_signature_returns_401(async_client, monkeypatch):
    _configure_webhook_secret(monkeypatch)
    response = await _post_orange_webhook(
        async_client,
        _sample_payload(),
        signature="not-a-valid-signature",
    )
    assert response.status_code == 401, response.text
    assert response.json()["error_code"] == "AUTH_FAILED"


@pytest.mark.asyncio
async def test_enriches_engagement_and_user_from_pbb(async_client, test_db_session, monkeypatch):
    _configure_webhook_secret(monkeypatch)

    engagement_id = 8802
    ep_id = 88021
    user_id = 88022
    city_request_id = "BLR5383272"

    await _seed_engagement(test_db_session, engagement_id, "OH8802")
    await _seed_participant(test_db_session, ep_id=ep_id, engagement_id=engagement_id, user_id=user_id)
    await test_db_session.execute(
        text(
            "INSERT INTO participant_blood_bookings "
            "(id, engagement_participant_id, relation, status, booking_id, diagnostic_provider, request_id) "
            "VALUES (880221, :ep, 'primary', 1, :bid, 'orange_health', :bid) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"ep": ep_id, "bid": city_request_id},
    )
    await test_db_session.commit()

    payload = _sample_payload(city_request_id=city_request_id, partner_reference_id=str(user_id))
    response = await _post_orange_webhook(async_client, payload, event_id=str(uuid.uuid4()))
    assert response.status_code == 200, response.text
    sync_log_id = response.json()["data"]["sync_log_id"]

    row = (
        await test_db_session.execute(
            text(
                "SELECT engagement_id, user_id FROM integration_sync_logs "
                "WHERE sync_log_id = :sync_log_id"
            ),
            {"sync_log_id": sync_log_id},
        )
    ).mappings().one()
    assert row["engagement_id"] == engagement_id
    assert row["user_id"] == user_id
