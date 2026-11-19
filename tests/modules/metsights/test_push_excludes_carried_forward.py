"""Ensure load-prev (is_carried_forward) answers are never pushed to Metsights."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from core.config import settings
from core.exceptions import AppError
from modules.assessments.dependencies import get_assessments_service
from modules.assessments.models import AssessmentInstance, AssessmentPackage, AssessmentPackageCategory
from modules.engagements.dependencies import get_engagements_service
from modules.metsights.client import MetsightsClient
from modules.metsights.service import MetsightsService
from modules.metsights.sync_service import MetsightsSyncService
from modules.platform_settings.dependencies import get_platform_settings_service_readonly
from modules.questionnaire.models import QuestionnaireResponse
from modules.questionnaire.repository import QuestionnaireRepository
from modules.users.repository import UsersRepository
from tests.modules.metsights.test_metsights_missing_greenlet import _ensure_manual_metsights_category
from tests.modules.questionnaire.test_questionnaire_user_routes import _ensure_test_engagement


@pytest.mark.asyncio
async def test_push_category_ignores_carried_forward_responses(test_db_session, monkeypatch):
    await _ensure_test_engagement(test_db_session)

    uid = 1
    phys_cat = await _ensure_manual_metsights_category(
        test_db_session,
        category_id=99511,
        category_key="physical-measurement",
        display_name="Physical Measurement CF",
        question_keys=["height", "weight"],
    )

    pkg_id = 99512
    test_db_session.add(
        AssessmentPackage(
            package_id=pkg_id,
            package_code="CF_PUSH_PKG",
            display_name="CarriedForward Push",
            assessment_type_code="1",
            status="active",
        )
    )
    test_db_session.add(
        AssessmentPackageCategory(package_id=pkg_id, category_id=int(phys_cat.category_id))
    )
    await test_db_session.commit()

    aid = 99513
    rid = "MS-CF-PUSH-01"
    test_db_session.add(
        AssessmentInstance(
            assessment_instance_id=aid,
            user_id=uid,
            package_id=pkg_id,
            engagement_id=1,
            status="active",
            metsights_record_id=rid,
        )
    )
    for qid, val in ((1, 175.0), (2, 70.0)):
        test_db_session.add(
            QuestionnaireResponse(
                assessment_instance_id=aid,
                question_id=qid,
                category_ids=[int(phys_cat.category_id)],
                answer={"value": val, "unit": "0"},
                is_carried_forward=True,
            )
        )
    await test_db_session.commit()

    async def _fake_detail(self, *, record_id: str, **kwargs):
        return {"id": record_id, "assessment_code": "MET_BASIC", "assessment_type": "MetSights Basic"}

    async def _fake_options(self, *, record_id: str, resource: str, **kwargs):
        return {}

    upsert_calls: list[dict] = []

    async def _fake_upsert(self, *, record_id: str, resource: str, body: dict, **kwargs):
        upsert_calls.append({"record_id": record_id, "resource": resource, "body": body})
        return {}

    monkeypatch.setattr(settings, "METSIGHTS_API_KEY", "test-key")
    monkeypatch.setattr(MetsightsService, "get_record_detail", _fake_detail)
    monkeypatch.setattr(MetsightsService, "options_record_subresource", _fake_options)
    monkeypatch.setattr(MetsightsService, "upsert_record_subresource", _fake_upsert)

    sync_service = MetsightsSyncService(
        metsights_service=MetsightsService(client=MetsightsClient()),
        users_repository=UsersRepository(),
        engagements_service=get_engagements_service(),
        assessments_service=get_assessments_service(),
        platform_settings_service=get_platform_settings_service_readonly(),
        questionnaire_repository=QuestionnaireRepository(),
    )

    with pytest.raises(AppError) as exc_info:
        await sync_service._push_category_to_metsights(
            test_db_session,
            assessment_instance_id=aid,
            user_id=uid,
            category_key="physical-measurement",
            category_of="metsights",
        )

    assert exc_info.value.status_code == 422
    assert upsert_calls == []


@pytest.mark.asyncio
async def test_carried_forward_bp_treated_as_missing_for_vitals_draft(test_db_session):
    vitals_ready = (
        await test_db_session.execute(
            text(
                "SELECT 1 FROM questionnaire_categories qc "
                "JOIN questionnaire_category_questions ccq ON ccq.category_id = qc.category_id "
                "JOIN questionnaire_definitions qd ON qd.question_id = ccq.question_id "
                "WHERE qc.category_key = 'vitals' AND qc.category_of = 'metsights' "
                "AND qd.question_key = 'systolic_blood_pressure' LIMIT 1"
            )
        )
    ).scalar_one_or_none()
    if vitals_ready is None:
        pytest.skip("vitals category/questions not wired in test database")

    from modules.assessments.dependencies import get_assessments_service
    from modules.assessments.models import AssessmentInstance
    from tests.modules.notifications.test_load_bioai_reports_vitals_fallback import (
        _seed_bioai_participant,
    )

    await _seed_bioai_participant(
        test_db_session,
        user_id=199203,
        engagement_id=199203,
        assessment_id=199203,
    )
    assessments_service = get_assessments_service()

    systolic_id = (
        await test_db_session.execute(
            text("SELECT question_id FROM questionnaire_definitions WHERE question_key = 'systolic_blood_pressure'")
        )
    ).scalar_one()
    diastolic_id = (
        await test_db_session.execute(
            text("SELECT question_id FROM questionnaire_definitions WHERE question_key = 'diastolic_blood_pressure'")
        )
    ).scalar_one()
    vitals_category_id = (
        await test_db_session.execute(
            text(
                "SELECT category_id FROM questionnaire_categories "
                "WHERE category_key = 'vitals' AND category_of = 'metsights'"
            )
        )
    ).scalar_one()

    for qid, val in ((int(systolic_id), 130.0), (int(diastolic_id), 85.0)):
        test_db_session.add(
            QuestionnaireResponse(
                assessment_instance_id=199203,
                question_id=qid,
                category_ids=[int(vitals_category_id)],
                answer={"value": val, "unit": "0"},
                is_carried_forward=True,
            )
        )
    await test_db_session.commit()

    assert await assessments_service.is_vitals_blood_pressure_missing(
        test_db_session,
        assessment_instance_id=199203,
    )

    result = await assessments_service.draft_vitals_blood_pressure_fallbacks(
        test_db_session,
        user_id=199203,
        assessment_instance_id=199203,
    )
    await test_db_session.commit()

    assert result["responses_drafted"] == 2
    rows = (
        await test_db_session.execute(
            text(
                "SELECT is_carried_forward FROM questionnaire_responses "
                "WHERE assessment_instance_id = 199203"
            )
        )
    ).scalars().all()
    assert all(cf is False for cf in rows)