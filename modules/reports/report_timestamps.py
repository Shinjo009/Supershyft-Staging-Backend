"""Stamp helpers for report_received_at / consultation_done_at KPI columns."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_url(url: str | None) -> str | None:
    value = (url or "").strip()
    return value or None


def set_diagnostic_report_url(target: Any, url: str | None) -> None:
    """Set blood diagnostic_report_url and stamp/clear report_received_at."""
    new_url = _normalize_url(url)
    old_url = _normalize_url(getattr(target, "diagnostic_report_url", None))
    target.diagnostic_report_url = new_url
    if new_url:
        if not old_url or getattr(target, "report_received_at", None) is None:
            target.report_received_at = _utcnow()
    else:
        target.report_received_at = None


def set_bioai_report_url(target: Any, url: str | None) -> None:
    """Set IHR report_url and stamp/clear report_received_at."""
    new_url = _normalize_url(url)
    old_url = _normalize_url(getattr(target, "report_url", None))
    target.report_url = new_url
    if new_url:
        if not old_url or getattr(target, "report_received_at", None) is None:
            target.report_received_at = _utcnow()
    else:
        target.report_received_at = None


def mark_consultation_done(booking: Any) -> None:
    """Flip consultation done and stamp consultation_done_at when newly done."""
    was_done = bool(getattr(booking, "done", False))
    booking.done = True
    if not was_done or getattr(booking, "consultation_done_at", None) is None:
        booking.consultation_done_at = _utcnow()
