"""Unit tests for bio-ai-reports PDF registration."""

from __future__ import annotations

from datetime import timedelta

import pytest

from modules.bioai_report.pdf_registration import (
    apply_assessment_date_override,
    bioreport_generate_endpoint,
    bioreport_regenerate_endpoint,
    extract_registered_report_url,
    extract_slug_from_report_url,
    lookup_first_registered_bio_ai_report_url,
    lookup_original_bio_ai_assessment_date,
    register_permanent_bio_ai_report_url,
    regenerate_permanent_bio_ai_report_url,
    resolve_canonical_bio_ai_report_url,
    summarize_bioreport_payload,
)
from modules.audit.models import IntegrationSyncLog


def test_summarize_bioreport_payload():
    payload = {
        "patient": {"name": "Jane Doe"},
        "report_metadata": {
            "record_id": "REC123",
            "disease_count": 4,
            "engine_version": "1.0.0",
        },
    }
    summary = summarize_bioreport_payload(payload)
    assert summary == {
        "record_id": "REC123",
        "patient_name": "Jane Doe",
        "disease_count": 4,
        "engine_version": "1.0.0",
        "truncated": True,
    }


def test_extract_registered_report_url_success():
    assert extract_registered_report_url({"url": "https://bio-ai-reports.supershyft.com/r/abc"}) == (
        "https://bio-ai-reports.supershyft.com/r/abc"
    )


def test_extract_registered_report_url_missing():
    with pytest.raises(Exception) as exc:
        extract_registered_report_url({"slug": "abc"})
    assert exc.value.error_code == "BIO_AI_REPORTS_ERROR"


def test_extract_slug_from_report_url_success():
    assert extract_slug_from_report_url(
        "https://bio-ai-reports.supershyft.com/r/A2Gp3Y2beG8i-4EjRaItnA"
    ) == "A2Gp3Y2beG8i-4EjRaItnA"


def test_extract_slug_from_report_url_with_query():
    assert extract_slug_from_report_url(
        "https://bio-ai-reports.supershyft.com/r/abc?dl=1"
    ) == "abc"


def test_extract_slug_from_report_url_missing():
    assert extract_slug_from_report_url("https://example.com/report.pdf") is None


def test_bioreport_regenerate_endpoint(monkeypatch):
    monkeypatch.setattr(
        "modules.bioai_report.pdf_registration.settings.BIO_AI_REPORTS_BASE_URL",
        "https://bio-ai-reports.supershyft.com",
    )
    assert bioreport_regenerate_endpoint() == (
        "https://bio-ai-reports.supershyft.com/api/reports/regenerate"
    )


@pytest.mark.asyncio
async def test_regenerate_permanent_bio_ai_report_url_calls_client(monkeypatch):
    monkeypatch.setattr(
        "modules.bioai_report.pdf_registration.settings.BIO_AI_REPORTS_BASE_URL",
        "https://bio-ai-reports.supershyft.com",
    )
    captured: dict[str, object] = {}

    class FakeClient:
        async def regenerate_report(self, payload, *, slug):
            captured["payload"] = payload
            captured["slug"] = slug
            return {
                "slug": slug,
                "url": "https://bio-ai-reports.supershyft.com/r/existing-slug",
            }

    async def fake_generate(*args, **kwargs):
        return {"patient": {"name": "Jane"}, "report_metadata": {"record_id": "R1"}}

    async def fake_tracked(db, *, provider, api_url, engagement_id, user_id, request_payload, operation, reraise=True):
        captured.setdefault("api_urls", []).append(api_url)
        return await operation()

    monkeypatch.setattr(
        "modules.bioai_report.pdf_registration._generate_bioreport_payload",
        fake_generate,
    )
    monkeypatch.setattr(
        "modules.bioai_report.pdf_registration.tracked_integration_call",
        fake_tracked,
    )

    url = await regenerate_permanent_bio_ai_report_url(
        db=None,
        assessment_instance_id=42,
        report_url="https://bio-ai-reports.supershyft.com/r/existing-slug",
        engagement_id=7,
        user_id=9,
        bio_ai_reports_client=FakeClient(),
    )
    assert url == "https://bio-ai-reports.supershyft.com/r/existing-slug"
    assert captured["slug"] == "existing-slug"
    assert bioreport_regenerate_endpoint() in captured["api_urls"]


@pytest.mark.asyncio
async def test_register_permanent_bio_ai_report_url_reuses_existing_without_api_call(
    test_db_session,
    monkeypatch,
):
    register_called = {"count": 0}

    class FakeClient:
        async def register_report(self, payload):
            register_called["count"] += 1
            return {"url": "https://bio-ai-reports.supershyft.com/r/new-slug"}

    async def _fake_lookup(*args, **kwargs):
        return "https://bio-ai-reports.supershyft.com/r/original-slug"

    monkeypatch.setattr(
        "modules.bioai_report.pdf_registration.lookup_existing_bio_ai_report_url",
        _fake_lookup,
    )

    url = await register_permanent_bio_ai_report_url(
        test_db_session,
        assessment_instance_id=99001,
        engagement_id=99001,
        user_id=99001,
        bio_ai_reports_client=FakeClient(),
    )
    assert url == "https://bio-ai-reports.supershyft.com/r/original-slug"
    assert register_called["count"] == 0


@pytest.mark.asyncio
async def test_lookup_first_registered_bio_ai_report_url(test_db_session, monkeypatch):
    from tests.modules.notifications.test_regenerate_bioai_reports import _seed_regenerate_participant

    monkeypatch.setattr(
        "modules.bioai_report.pdf_registration.settings.BIO_AI_REPORTS_BASE_URL",
        "https://bio-ai-reports.supershyft.com",
    )
    from datetime import datetime, timezone

    await _seed_regenerate_participant(
        test_db_session,
        user_id=99002,
        engagement_id=99002,
        assessment_id=99002,
        report_url=None,
    )
    test_db_session.add(
        IntegrationSyncLog(
            user_id=99002,
            engagement_id=99002,
            provider="bio_ai_reports",
            api_endpoint_url="https://bio-ai-reports.supershyft.com/api/reports",
            status="success",
            response_payload={
                "url": "https://bio-ai-reports.supershyft.com/r/first-slug",
                "slug": "first-slug",
            },
            created_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
        )
    )
    test_db_session.add(
        IntegrationSyncLog(
            user_id=99002,
            engagement_id=99002,
            provider="bio_ai_reports",
            api_endpoint_url="https://bio-ai-reports.supershyft.com/api/reports",
            status="success",
            response_payload={
                "url": "https://bio-ai-reports.supershyft.com/r/later-slug",
                "slug": "later-slug",
            },
            created_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
        )
    )
    await test_db_session.commit()

    url = await lookup_first_registered_bio_ai_report_url(
        test_db_session,
        user_id=99002,
        engagement_id=99002,
    )
    assert url == "https://bio-ai-reports.supershyft.com/r/first-slug"


@pytest.mark.asyncio
async def test_resolve_canonical_bio_ai_report_url_prefers_first_register(test_db_session, monkeypatch):
    from tests.modules.notifications.test_regenerate_bioai_reports import _seed_regenerate_participant

    monkeypatch.setattr(
        "modules.bioai_report.pdf_registration.settings.BIO_AI_REPORTS_BASE_URL",
        "https://bio-ai-reports.supershyft.com",
    )
    from datetime import datetime, timezone

    await _seed_regenerate_participant(
        test_db_session,
        user_id=99003,
        engagement_id=99003,
        assessment_id=99003,
        report_url="https://bio-ai-reports.supershyft.com/r/later-slug",
    )
    test_db_session.add(
        IntegrationSyncLog(
            user_id=99003,
            engagement_id=99003,
            provider="bio_ai_reports",
            api_endpoint_url="https://bio-ai-reports.supershyft.com/api/reports",
            status="success",
            response_payload={
                "url": "https://bio-ai-reports.supershyft.com/r/first-slug",
            },
            created_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
        )
    )
    await test_db_session.commit()

    url = await resolve_canonical_bio_ai_report_url(
        test_db_session,
        user_id=99003,
        engagement_id=99003,
        assessment_instance_id=99003,
        report_url="https://bio-ai-reports.supershyft.com/r/later-slug",
    )
    assert url == "https://bio-ai-reports.supershyft.com/r/first-slug"


def test_apply_assessment_date_override_updates_nested_blocks():
    payload = {
        "patient": {"name": "Jane", "assessment_date": "2026-09-14T10:00:00+05:30"},
        "executive_summary": {
            "assessment_date": "2026-09-14T10:00:00+05:30",
            "patient": {"name": "Jane", "assessment_date": "2026-09-14T10:00:00+05:30"},
        },
    }
    apply_assessment_date_override(payload, "2026-08-29T09:00:00+05:30")
    assert payload["patient"]["assessment_date"] == "2026-08-29T09:00:00+05:30"
    assert payload["executive_summary"]["assessment_date"] == "2026-08-29T09:00:00+05:30"
    assert payload["executive_summary"]["patient"]["assessment_date"] == "2026-08-29T09:00:00+05:30"


@pytest.mark.asyncio
async def test_lookup_original_bio_ai_assessment_date_prefers_earliest_generate_log(
    test_db_session,
):
    from datetime import datetime, timezone

    from tests.modules.notifications.test_regenerate_bioai_reports import _seed_regenerate_participant

    assessment_id = 99004
    original_date = "2026-08-29T09:00:00+05:30"
    latest_date = "2026-09-14T10:00:00+05:30"
    generate_endpoint = bioreport_generate_endpoint(assessment_id)

    await _seed_regenerate_participant(
        test_db_session,
        user_id=99004,
        engagement_id=99004,
        assessment_id=assessment_id,
        report_url=None,
    )
    test_db_session.add(
        IntegrationSyncLog(
            user_id=99004,
            engagement_id=99004,
            provider="bio_ai_reports",
            api_endpoint_url=generate_endpoint,
            status="success",
            response_payload={
                "patient": {"assessment_date": original_date},
                "executive_summary": {"assessment_date": original_date},
            },
            created_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
        )
    )
    test_db_session.add(
        IntegrationSyncLog(
            user_id=99004,
            engagement_id=99004,
            provider="bio_ai_reports",
            api_endpoint_url=generate_endpoint,
            status="success",
            response_payload={
                "patient": {"assessment_date": latest_date},
                "executive_summary": {"assessment_date": latest_date},
            },
            created_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
        )
    )
    await test_db_session.commit()

    date_value = await lookup_original_bio_ai_assessment_date(
        test_db_session,
        assessment_instance_id=assessment_id,
        user_id=99004,
        engagement_id=99004,
    )
    assert date_value == original_date


@pytest.mark.asyncio
async def test_lookup_original_bio_ai_assessment_date_falls_back_to_engagement_date(
    test_db_session,
):
    from datetime import date

    from tests.modules.notifications.test_regenerate_bioai_reports import _seed_regenerate_participant

    assessment_id = 99005
    await _seed_regenerate_participant(
        test_db_session,
        user_id=99005,
        engagement_id=99005,
        assessment_id=assessment_id,
        report_url=None,
    )
    await test_db_session.commit()

    date_value = await lookup_original_bio_ai_assessment_date(
        test_db_session,
        assessment_instance_id=assessment_id,
        user_id=99005,
        engagement_id=99005,
    )
    assert date_value == (date.today() - timedelta(days=1)).isoformat()


@pytest.mark.asyncio
async def test_regenerate_preserves_original_assessment_date(monkeypatch, test_db_session):
    monkeypatch.setattr(
        "modules.bioai_report.pdf_registration.settings.BIO_AI_REPORTS_BASE_URL",
        "https://bio-ai-reports.supershyft.com",
    )
    from datetime import datetime, timezone

    from tests.modules.notifications.test_regenerate_bioai_reports import _seed_regenerate_participant

    assessment_id = 99006
    original_date = "2026-08-29T09:00:00+05:30"
    today_date = "2026-09-14T10:00:00+05:30"
    generate_endpoint = bioreport_generate_endpoint(assessment_id)

    await _seed_regenerate_participant(
        test_db_session,
        user_id=99006,
        engagement_id=99006,
        assessment_id=assessment_id,
        report_url="https://bio-ai-reports.supershyft.com/r/existing-slug",
    )

    test_db_session.add(
        IntegrationSyncLog(
            user_id=99006,
            engagement_id=99006,
            provider="bio_ai_reports",
            api_endpoint_url=generate_endpoint,
            status="success",
            response_payload={
                "patient": {"assessment_date": original_date},
                "executive_summary": {"assessment_date": original_date},
            },
            created_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
        )
    )
    await test_db_session.commit()

    captured: dict[str, object] = {}

    class FakeClient:
        async def regenerate_report(self, payload, *, slug):
            captured["payload"] = payload
            captured["slug"] = slug
            return {
                "slug": slug,
                "url": "https://bio-ai-reports.supershyft.com/r/existing-slug",
            }

    async def fake_generate(*args, **kwargs):
        return {
            "patient": {"name": "Jane", "assessment_date": today_date},
            "executive_summary": {
                "assessment_date": today_date,
                "patient": {"name": "Jane", "assessment_date": today_date},
            },
            "report_metadata": {"record_id": "R1"},
        }

    async def fake_tracked(db, *, provider, api_url, engagement_id, user_id, request_payload, operation, reraise=True):
        return await operation()

    monkeypatch.setattr(
        "modules.bioai_report.pdf_registration._generate_bioreport_payload",
        fake_generate,
    )
    monkeypatch.setattr(
        "modules.bioai_report.pdf_registration.tracked_integration_call",
        fake_tracked,
    )

    url = await regenerate_permanent_bio_ai_report_url(
        test_db_session,
        assessment_instance_id=assessment_id,
        report_url="https://bio-ai-reports.supershyft.com/r/existing-slug",
        engagement_id=99006,
        user_id=99006,
        bio_ai_reports_client=FakeClient(),
    )
    assert url == "https://bio-ai-reports.supershyft.com/r/existing-slug"
    payload = captured["payload"]
    assert payload["patient"]["assessment_date"] == original_date
    assert payload["executive_summary"]["assessment_date"] == original_date
    assert payload["executive_summary"]["patient"]["assessment_date"] == original_date
