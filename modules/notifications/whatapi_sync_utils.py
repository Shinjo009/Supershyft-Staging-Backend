"""Shared helpers for WhatAPI integration_sync_logs (webhook URL redaction)."""

from __future__ import annotations

from urllib.parse import urlparse


def redact_whatapi_webhook_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
