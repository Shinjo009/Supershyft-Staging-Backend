"""Tests for Alembic 0187 notification content backfill."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from db.seed.data import DEFAULT_NOTIFICATION_SERVICES

LEGACY_EVENT_CODES = (
    "onboarding",
    "pretest_guidelines",
    "questionnaire_reminder_before",
    "questionnaire_reminder_after",
    "blood_report_ready",
    "bioai_report_ready",
    "consultation_ready",
    "consultation_remainder",
    "consultation_booking_alert",
    "booking_guide",
    "report_ready",
)

MAPPED_EVENT_CODES = (
    "onboarding.completed",
    "collection.reminder.pretest",
    "assessment.reminder.before",
    "assessment.reminder.after",
    "report.blood.ready",
    "report.bioai.ready",
    "consultation.ready",
    "consultation.reminder",
    "consultation.booked",
    "collection.reminder.booking_guide",
    "report.vifc.ready",
)


@pytest.mark.asyncio
async def test_default_notification_services_have_direct_content(test_db_session):
    for seed in DEFAULT_NOTIFICATION_SERVICES:
        row = (
            await test_db_session.execute(
                text(
                    "SELECT template_name, email_subject, email_body, email_html, channel "
                    "FROM notification_services WHERE service_key = :key"
                ),
                {"key": seed.service_key},
            )
        ).mappings().first()
        assert row is not None, seed.service_key
        if row["channel"] == "whatsapp":
            assert (row["template_name"] or "").strip(), seed.service_key
        else:
            assert (row["email_subject"] or row["email_body"] or row["email_html"]), seed.service_key


@pytest.mark.asyncio
async def test_production_report_email_keys_have_content_when_present(test_db_session):
    for key in ("send-reports-email", "send-blood-report-email-v2"):
        row = (
            await test_db_session.execute(
                text(
                    "SELECT email_subject, email_body FROM notification_services WHERE service_key = :key"
                ),
                {"key": key},
            )
        ).mappings().first()
        if row is None:
            continue
        assert (row["email_subject"] or row["email_body"]), key


@pytest.mark.asyncio
async def test_global_bindings_exist_for_mapped_legacy_events(test_db_session):
    for mapped in MAPPED_EVENT_CODES:
        count = (
            await test_db_session.execute(
                text("SELECT COUNT(*) FROM notification_events WHERE event_code = :code"),
                {"code": mapped},
            )
        ).scalar_one()
        assert int(count) >= 1, mapped


@pytest.mark.asyncio
async def test_engagement_notifications_use_catalog_event_codes(test_db_session):
    rows = (
        await test_db_session.execute(
            text(
                "SELECT DISTINCT event_code FROM engagement_notifications WHERE event_code IS NOT NULL"
            )
        )
    ).scalars().all()
    for code in rows:
        if code in LEGACY_EVENT_CODES:
            pytest.fail(f"engagement_notifications still has legacy event_code={code}")


@pytest.mark.asyncio
async def test_content_artifact_is_valid_json():
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "db" / "migrations" / "data" / "0187_notification_content.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) >= 60
