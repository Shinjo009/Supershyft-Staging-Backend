"""Unit tests for WhatAPI webhook payload extraction."""

from __future__ import annotations

from modules.notifications.whatapi_webhook_handler import (
    _walk_for_queue_status,
    extract_status_events,
)


def test_walk_finds_queue_id_and_message_status():
    payload = {
        "message": {
            "queue_id": "q-1",
            "message_status": "failed",
            "errors": [{"title": "Template mismatch"}],
        }
    }
    pairs = _walk_for_queue_status(payload)
    assert ("q-1", "failed", "Template mismatch") in pairs


def test_walk_meta_statuses_with_ancestor_queue_id():
    payload = {
        "queue_id": "q-2",
        "entry": [{"changes": [{"value": {"statuses": [{"status": "delivered"}]}}]}],
    }
    pairs = _walk_for_queue_status(payload)
    assert any(q == "q-2" and status == "delivered" for q, status, _ in pairs)


def test_extract_meta_wamid_failed_status():
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
                                    "id": "wamid.HBgMOTEwMDAwMDE3MDAwFQIAERgSNjBEREI4MzI0MkJCNEUyRjk3AA==",
                                    "status": "failed",
                                    "recipient_id": "910000017000",
                                    "errors": [{"title": "Message undeliverable"}],
                                }
                            ],
                        }
                    }
                ]
            }
        ],
    }
    events = extract_status_events(payload)
    meta = [e for e in events if e.source == "meta"]
    assert len(meta) == 1
    assert meta[0].wamid.startswith("wamid.")
    assert meta[0].status == "failed"
    assert meta[0].recipient_id == "910000017000"
    assert meta[0].detail == "Message undeliverable"


def test_walk_ignores_wamid_only_for_queue_walker():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "statuses": [{"id": "wamid.xxx", "status": "failed"}],
                        }
                    }
                ]
            }
        ]
    }
    assert _walk_for_queue_status(payload) == []
    assert len(extract_status_events(payload)) == 1
