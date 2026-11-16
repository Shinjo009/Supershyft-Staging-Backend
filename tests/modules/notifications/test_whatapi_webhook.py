"""Tests for GET/POST /webhooks/whatapi."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from core.config import settings
from modules.notifications.models import Notification


async def _seed_service(test_db_session, *, service_key: str) -> None:
    await test_db_session.execute(
        text(
            "INSERT INTO notification_services "
            "(service_key, display_name, channel, template_name, email_subject, email_body, is_active, require_blood_report_url, require_bio_ai_report_url, require_participant_detail) "
            "VALUES (:sk, :dn, 'whatsapp', 'test_tpl', NULL, NULL, true, false, false, false) "
            "ON CONFLICT (service_key) DO NOTHING"
        ),
        {"sk": service_key, "dn": service_key},
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_whatapi_get_challenge_echoes_plain_text(async_client, monkeypatch):
    monkeypatch.setattr(settings, "WHATAPI_WEBHOOK_VERIFY_TOKEN", "verify-me")
    resp = await async_client.get(
        "/webhooks/whatapi",
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "TEST123",
            "hub.verify_token": "verify-me",
        },
    )
    assert resp.status_code == 200
    assert resp.text == "TEST123"
    assert "text/plain" in resp.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_whatapi_get_rejects_bad_verify_token(async_client, monkeypatch):
    monkeypatch.setattr(settings, "WHATAPI_WEBHOOK_VERIFY_TOKEN", "verify-me")
    resp = await async_client.get(
        "/webhooks/whatapi",
        params={
            "hub.challenge": "TEST123",
            "hub.verify_token": "wrong",
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_whatapi_get_challange_typo_param(async_client, monkeypatch):
    monkeypatch.setattr(settings, "WHATAPI_WEBHOOK_VERIFY_TOKEN", "")
    resp = await async_client.get(
        "/webhooks/whatapi",
        params={"challange": "TYPO-CHAL", "echo": "true"},
    )
    assert resp.status_code == 200
    assert resp.text == "TYPO-CHAL"


@pytest.mark.asyncio
async def test_whatapi_post_updates_notification_by_queue_id(
    async_client, test_db_session, monkeypatch
):
    service_key = "whatapi-wh-test"
    await _seed_service(test_db_session, service_key=service_key)
    queue_id = "887c0d94-e0bd-49fe-98b3-955e81f9ed47"
    notification = Notification(
        service_key=service_key,
        status="pending",
        channel="whatsapp",
        user={"contacts": ["919362830757"]},
        message="queued",
        queue_id=queue_id,
        dispatched_at=datetime.now(timezone.utc),
    )
    test_db_session.add(notification)
    await test_db_session.commit()
    await test_db_session.refresh(notification)

    payload = {
        "message": {
            "queue_id": queue_id,
            "message_status": "delivered",
        }
    }
    resp = await async_client.post("/webhooks/whatapi", json=payload)
    assert resp.status_code == 200

    await test_db_session.refresh(notification)
    assert notification.status == "sent"
    assert notification.completed_at is not None
    assert notification.message == "WhatsApp delivered (delivered)"


@pytest.mark.asyncio
async def test_whatapi_post_updates_message_on_failed(
    async_client, test_db_session, monkeypatch
):
    service_key = "whatapi-wh-fail"
    await _seed_service(test_db_session, service_key=service_key)
    queue_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    notification = Notification(
        service_key=service_key,
        status="pending",
        channel="whatsapp",
        user={"contacts": ["919876543210"]},
        message="WhatsApp template queued via WhatAPI POST",
        queue_id=queue_id,
        dispatched_at=datetime.now(timezone.utc),
    )
    test_db_session.add(notification)
    await test_db_session.commit()
    await test_db_session.refresh(notification)

    payload = {
        "message": {
            "queue_id": queue_id,
            "message_status": "failed",
            "errors": [{"title": "Message undeliverable"}],
        }
    }
    resp = await async_client.post("/webhooks/whatapi", json=payload)
    assert resp.status_code == 200

    await test_db_session.refresh(notification)
    assert notification.status == "failed"
    assert "undeliverable" in (notification.message or "").lower()


@pytest.mark.asyncio
async def test_whatapi_post_meta_envelope_with_queue_and_statuses(
    async_client, test_db_session,
):
    service_key = "whatapi-wh-meta"
    await _seed_service(test_db_session, service_key=service_key)
    queue_id = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
    notification = Notification(
        service_key=service_key,
        status="pending",
        channel="whatsapp",
        user={"contacts": ["919876543210"]},
        message="queued",
        queue_id=queue_id,
        dispatched_at=datetime.now(timezone.utc),
    )
    test_db_session.add(notification)
    await test_db_session.commit()
    await test_db_session.refresh(notification)

    payload = {
        "queue_id": queue_id,
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {
                                    "status": "delivered",
                                    "id": "wamid.IGNORED",
                                }
                            ]
                        }
                    }
                ]
            }
        ],
    }
    resp = await async_client.post("/webhooks/whatapi", json=payload)
    assert resp.status_code == 200

    await test_db_session.refresh(notification)
    assert notification.status == "sent"


@pytest.mark.asyncio
async def test_whatapi_post_meta_failed_without_queue_id(
    async_client, test_db_session,
):
    from modules.users.models import User

    service_key = "whatapi-wh-meta-fail"
    await _seed_service(test_db_session, service_key=service_key)
    test_db_session.add(
        User(
            user_id=97001,
            age=30,
            phone="0000017000",
            status="active",
            email="meta-fail@example.com",
        )
    )
    await test_db_session.flush()

    queue_id = "8a0b1daa-a697-4616-9d9e-5913a61677f3"
    notification = Notification(
        service_key=service_key,
        status="sent",
        channel="whatsapp",
        user={"user_ids": [97001]},
        message="WhatsApp delivered (sent)",
        queue_id=queue_id,
        dispatched_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    test_db_session.add(notification)
    await test_db_session.commit()
    await test_db_session.refresh(notification)

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "1658253265196050",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "phone_number_id": "1068820602977269",
                                "display_phone_number": "917977842511",
                            },
                            "statuses": [
                                {
                                    "id": "wamid.HBgMOTEwMDAwMDE3MDAwFQIAERgSNjBEREI4MzI0MkJCNEUyRjk3AA==",
                                    "status": "failed",
                                    "timestamp": "1794468988",
                                    "recipient_id": "910000017000",
                                    "errors": [
                                        {
                                            "code": 131026,
                                            "title": "Message undeliverable",
                                            "message": "Message undeliverable",
                                        }
                                    ],
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    resp = await async_client.post("/webhooks/whatapi", json=payload)
    assert resp.status_code == 200
    assert resp.json()["data"]["updated"] == 1

    await test_db_session.refresh(notification)
    assert notification.status == "failed"
    assert "undeliverable" in (notification.message or "").lower()
    assert notification.whatsapp_message_id.startswith("wamid.")


@pytest.mark.asyncio
async def test_whatapi_post_meta_sent_keeps_pending(async_client, test_db_session):
    service_key = "whatapi-wh-meta-sent"
    await _seed_service(test_db_session, service_key=service_key)
    queue_id = "c3d4e5f6-a7b8-9012-cdef-123456789abc"
    wamid = "wamid.test.sent.pending"
    notification = Notification(
        service_key=service_key,
        status="pending",
        channel="whatsapp",
        user={"contacts": [{"phone": "8762830757"}]},
        message="queued",
        queue_id=queue_id,
        dispatched_at=datetime.now(timezone.utc),
    )
    test_db_session.add(notification)
    await test_db_session.commit()
    await test_db_session.refresh(notification)

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "statuses": [
                                {
                                    "id": wamid,
                                    "status": "sent",
                                    "recipient_id": "918762830757",
                                }
                            ],
                        }
                    }
                ]
            }
        ],
    }
    resp = await async_client.post("/webhooks/whatapi", json=payload)
    assert resp.status_code == 200

    await test_db_session.refresh(notification)
    assert notification.status == "pending"
    assert notification.whatsapp_message_id == wamid
    assert notification.completed_at is None
    assert "awaiting delivery confirmation" in (notification.message or "").lower()


def _meta_status_payload(*, wamid: str, status: str, recipient_id: str = "918762830757") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "statuses": [
                                {
                                    "id": wamid,
                                    "status": status,
                                    "recipient_id": recipient_id,
                                }
                            ],
                        }
                    }
                ]
            }
        ],
    }


@pytest.mark.asyncio
async def test_whatapi_post_meta_out_of_order_sent_does_not_downgrade(
    async_client, test_db_session
):
    """Meta sometimes delivers `delivered` before a late `sent`; never downgrade."""
    service_key = "whatapi-wh-meta-ooo"
    await _seed_service(test_db_session, service_key=service_key)
    queue_id = "d4e5f6a7-b8c9-0123-def0-23456789abcd"
    wamid = "wamid.test.ooo.delivered.then.sent"
    notification = Notification(
        service_key=service_key,
        status="pending",
        channel="whatsapp",
        user={"contacts": [{"phone": "8762830757"}]},
        message="WhatsApp template queued via WhatAPI POST",
        queue_id=queue_id,
        dispatched_at=datetime.now(timezone.utc),
    )
    test_db_session.add(notification)
    await test_db_session.commit()
    await test_db_session.refresh(notification)

    delivered = await async_client.post(
        "/webhooks/whatapi",
        json=_meta_status_payload(wamid=wamid, status="delivered"),
    )
    assert delivered.status_code == 200
    await test_db_session.refresh(notification)
    assert notification.status == "sent"
    assert notification.completed_at is not None
    delivered_message = notification.message

    late_sent = await async_client.post(
        "/webhooks/whatapi",
        json=_meta_status_payload(wamid=wamid, status="sent"),
    )
    assert late_sent.status_code == 200
    await test_db_session.refresh(notification)
    assert notification.status == "sent"
    assert notification.completed_at is not None
    assert notification.message == delivered_message


@pytest.mark.asyncio
async def test_whatapi_ack_stores_wamid_from_response(async_client, test_db_session):
    service_key = "whatapi-wh-ack-wamid"
    await _seed_service(test_db_session, service_key=service_key)
    queue_id = "e5f6a7b8-c9d0-1234-ef01-3456789abcde"
    wamid = "wamid.HBgMOTE4NzYyODMwNzU3FQIAERgSTESTQUNLV0FNSUQAAA=="
    notification = Notification(
        service_key=service_key,
        status="pending",
        channel="whatsapp",
        user={"contacts": [{"phone": "8762830757"}]},
        message="queued",
        queue_id=queue_id,
        dispatched_at=datetime.now(timezone.utc),
    )
    test_db_session.add(notification)
    await test_db_session.commit()
    await test_db_session.refresh(notification)

    payload = {
        "message": {"queue_id": queue_id, "message_status": "sent"},
        "response": {
            "contacts": [{"input": "918762830757", "wa_id": "918762830757"}],
            "messages": [{"id": wamid, "message_status": "accepted"}],
            "messaging_product": "whatsapp",
        },
        "messaging_channel": "whatsapp",
    }
    resp = await async_client.post("/webhooks/whatapi", json=payload)
    assert resp.status_code == 200

    await test_db_session.refresh(notification)
    # WhatAPI queue "sent" maps to DB sent
    assert notification.status == "sent"
    assert notification.whatsapp_message_id == wamid
