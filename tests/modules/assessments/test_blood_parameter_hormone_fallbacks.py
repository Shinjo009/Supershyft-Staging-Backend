"""Tests for Pro female hormone placeholder refresh logic."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from modules.assessments.service import AssessmentsService, _should_replace_stale_hormone_placeholder


@pytest.mark.asyncio
async def test_redraft_blood_questionnaire_responses_orchestrates_report_then_fallbacks():
    service = AssessmentsService(AsyncMock())
    service.draft_blood_parameters_from_report = AsyncMock(
        return_value={"responses_drafted": 33}
    )
    service.draft_blood_parameter_internal_fallbacks = AsyncMock(
        return_value={"responses_drafted": 3, "fallback_keys": ["lh_value", "fsh_value", "testosterone"]}
    )

    result = await service.redraft_blood_questionnaire_responses(
        AsyncMock(),
        user_id=12399,
        assessment_instance_id=1049,
    )

    service.draft_blood_parameters_from_report.assert_awaited_once()
    service.draft_blood_parameter_internal_fallbacks.assert_awaited_once()
    assert result["responses_drafted"] == 36
    assert result["responses_drafted_from_report"] == 33
    assert result["responses_drafted_from_fallbacks"] == 3


def test_should_replace_legacy_lh_unit_zero():
    assert _should_replace_stale_hormone_placeholder(
        "lh_value",
        {"value": 5.0, "unit": "0"},
        target_value=5.0,
        target_unit="3",
    )


def test_should_replace_legacy_iu_l_interim_unit():
    assert _should_replace_stale_hormone_placeholder(
        "fsh_value",
        {"value": 5.0, "unit": "1"},
        target_value=5.0,
        target_unit="3",
    )


def test_should_replace_legacy_testosterone_ng_dl():
    assert _should_replace_stale_hormone_placeholder(
        "testosterone",
        {"value": 400.0, "unit": "0"},
        target_value=0.5,
        target_unit="2",
    )


def test_should_not_replace_correct_miu_ml_hormone_answer():
    assert not _should_replace_stale_hormone_placeholder(
        "lh_value",
        {"value": 5.77, "unit": "3"},
        target_value=5.0,
        target_unit="3",
    )


def test_should_not_replace_correct_ng_ml_testosterone():
    assert not _should_replace_stale_hormone_placeholder(
        "testosterone",
        {"value": 0.26, "unit": "2"},
        target_value=0.5,
        target_unit="2",
    )
