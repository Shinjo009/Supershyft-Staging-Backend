"""Tests for ensure_vitals_before_bio_ai_generation."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from modules.metsights.bio_ai_vitals_gate import ensure_vitals_before_bio_ai_generation


@pytest.mark.asyncio
async def test_ensure_vitals_noop_for_fitprint_type_code(test_db_session):
    assessments_service = AsyncMock()
    sync_service = AsyncMock()
    ok = await ensure_vitals_before_bio_ai_generation(
        test_db_session,
        assessments_service=assessments_service,
        sync_service=sync_service,
        user_id=1,
        engagement_id=1,
        assessment_instance_id=1,
        type_code="7",
    )
    assert ok is True
    assessments_service.is_vitals_blood_pressure_missing.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_vitals_drafts_and_pushes_when_bp_missing(test_db_session):
    assessments_service = AsyncMock()
    assessments_service.is_vitals_blood_pressure_missing = AsyncMock(return_value=True)
    assessments_service.draft_vitals_blood_pressure_fallbacks = AsyncMock(
        return_value={"responses_drafted": 2}
    )
    sync_service = AsyncMock()
    sync_service._push_category_to_metsights = AsyncMock(
        return_value={"fields_pushed": ["systolic_blood_pressure"]}
    )
    details: list[dict] = []

    ok = await ensure_vitals_before_bio_ai_generation(
        test_db_session,
        assessments_service=assessments_service,
        sync_service=sync_service,
        user_id=10,
        engagement_id=20,
        assessment_instance_id=30,
        type_code="1",
        details=details,
    )

    assert ok is True
    assessments_service.draft_vitals_blood_pressure_fallbacks.assert_awaited_once()
    sync_service._push_category_to_metsights.assert_awaited_once()
    assert any(d["action"] == "drafted" for d in details)
    assert any(d["action"] == "pushed" for d in details)


@pytest.mark.asyncio
async def test_ensure_vitals_returns_false_when_push_fails(test_db_session):
    assessments_service = AsyncMock()
    assessments_service.is_vitals_blood_pressure_missing = AsyncMock(return_value=False)
    sync_service = AsyncMock()
    sync_service._push_category_to_metsights = AsyncMock(side_effect=RuntimeError("push failed"))

    ok = await ensure_vitals_before_bio_ai_generation(
        test_db_session,
        assessments_service=assessments_service,
        sync_service=sync_service,
        user_id=10,
        engagement_id=20,
        assessment_instance_id=30,
        type_code="2",
    )

    assert ok is False