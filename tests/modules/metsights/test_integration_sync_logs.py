"""Tests for integration_sync_logs on Metsights questionnaire push/pull paths."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select, text

from core.config import settings
from core.security import create_jwt_token
from db.column_types import STATUS_INTEGRATION_SYNC, label_to_status_code
from modules.assessments.models import AssessmentInstance, AssessmentPackage, AssessmentPackageCategory
from modules.diagnostics.models import DiagnosticPackage
from modules.employee.models import Employee
from modules.engagements.models import Engagement, EngagementType
from modules.questionnaire.models import QuestionnaireCategory, QuestionnaireResponse
from modules.users.models import User
from tests.modules.questionnaire.test_questionnaire_user_routes import _ensure_test_engagement, _seed_user
from tests.modules.assessments.test_assessments_submit_routes import (
    _ensure_metsights_category,
    _ensure_category_questions_push_enabled,
    _ensure_question_push_enabled,
    _metsights_category_id,
)

_SYNC_SUCCESS = label_to_status_code(STATUS_INTEGRATION_SYNC, "success")
_SYNC_SKIPPED = label_to_status_code(STATUS_INTEGRATION_SYNC, "skipped")


def _employee_auth_header(employee_id: int) -> dict[str, str]:
    from tests.helpers.auth import employee_auth_header
    return employee_auth_header(employee_id)


def _user_auth_header(user_id: int) -> dict[str, str]:
    from tests.helpers.auth import user_auth_header
    return user_auth_header(user_id)


async def _seed_employee(test_db_session, *, user_id: int):
    test_db_session.add(User(user_id=user_id, age=30, phone=f"{user_id}0000000001", status="active"))
    await test_db_session.flush()
    test_db_session.add(Employee(employee_id=user_id, name=f"Employee {user_id}", phone=str(user_id).zfill(10)[:15], email=f"employee{user_id}@test.example", role="admin", status="active"))
    await test_db_session.commit()


async def _seed_push_engagement(test_db_session, *, engagement_id: int = 9701, package_id: int = 9702):
    diag_result = await test_db_session.execute(
        select(DiagnosticPackage).where(DiagnosticPackage.diagnostic_package_id == 1)
    )
    if diag_result.scalar_one_or_none() is None:
        test_db_session.add(
            DiagnosticPackage(
                diagnostic_package_id=1,
                reference_id="TEST_DIAG_PUSH",
                package_name="Test Diagnostic",
                diagnostic_provider="healthians",
                status="active",
            )
        )

    test_db_session.add(
        AssessmentPackage(
            package_id=package_id,
            package_code=f"METSIGHTS_PRO_LOG_{package_id}",
            display_name="Metsights Pro",
            assessment_type_code="2",
            status="active",
        )
    )
    await test_db_session.flush()

    engagement_type_id = (
        await test_db_session.execute(
            select(EngagementType.id).where(EngagementType.code == "bio_ai").limit(1)
        )
    ).scalar_one_or_none()

    existing = (
        await test_db_session.execute(
            select(Engagement).where(Engagement.engagement_id == engagement_id)
        )
    ).scalar_one_or_none()
    if existing is None:
        test_db_session.add(
            Engagement(
                engagement_id=engagement_id,
                engagement_name="Sync Log Camp",
                engagement_code=f"ENG-SYNC-{engagement_id}",
                engagement_type=engagement_type_id,
                assessment_package_id=package_id,
                diagnostic_package_id=1,
                city="BLR",
                slot_duration=20,
                start_date=date(2026, 2, 1),
                end_date=date(2026, 2, 28),
                status="running",
            )
        )

    test_db_session.add(AssessmentPackageCategory(package_id=package_id, category_id=1))
    await _ensure_metsights_category(
        test_db_session, category_id=1, category_key="physical-measurement"
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_push_questionnaires_creates_integration_sync_logs(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "METSIGHTS_API_KEY", "test-key")
    await _seed_employee(test_db_session, user_id=9701)
    await _seed_push_engagement(test_db_session)

    await _seed_user(test_db_session, user_id=5701)
    await _seed_user(test_db_session, user_id=5702)

    pushed_rid = "MS-PUSH-LOG-01"
    test_db_session.add(
        AssessmentInstance(
            assessment_instance_id=9703,
            user_id=5701,
            package_id=9702,
            engagement_id=9701,
            status="active",
            metsights_record_id=pushed_rid,
        )
    )
    test_db_session.add(
        QuestionnaireResponse(
            assessment_instance_id=9703,
            question_id=1,
            category_ids=[1],
            answer={"value": 175.0, "unit": "0"},
        )
    )
    test_db_session.add(
        AssessmentInstance(
            assessment_instance_id=9704,
            user_id=5702,
            package_id=9702,
            engagement_id=9701,
            status="active",
            metsights_record_id=None,
        )
    )
    await test_db_session.commit()

    async def _fake_upsert(self, *, record_id: str, resource: str, body: dict):
        return {}

    async def _fake_options(self, *, record_id: str, resource: str):
        return {}

    monkeypatch.setattr("modules.metsights.service.MetsightsService.upsert_record_subresource", _fake_upsert)
    monkeypatch.setattr("modules.metsights.service.MetsightsService.options_record_subresource", _fake_options)

    response = await async_client.post(
        "/engagements/9701/push-questionnaires",
        headers=_employee_auth_header(9701),
        json={"package_id": 9702},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["pushed"] == 1
    assert data["skipped"] == 1

    rows = (
        await test_db_session.execute(
            text(
                "SELECT engagement_id, user_id, api_endpoint_url, status, response_payload, request_payload "
                "FROM integration_sync_logs WHERE provider = 'metsights' "
                "AND engagement_id = 9701 ORDER BY sync_log_id"
            )
        )
    ).mappings().all()

    assert len(rows) >= 2

    skipped_rows = [r for r in rows if r["status"] == _SYNC_SKIPPED]
    assert any(r["user_id"] == 5702 for r in skipped_rows)
    assert any(
        r["response_payload"] and r["response_payload"].get("reason") == "no_metsights_record_id"
        for r in skipped_rows
    )

    push_rows = [r for r in rows if r["user_id"] == 5701 and r["status"] == _SYNC_SUCCESS]
    assert push_rows
    assert any("/physical-measurement/" in r["api_endpoint_url"] for r in push_rows)
    assert any(r["response_payload"] == {"pushed": True} for r in push_rows)
    assert any(r["request_payload"] and "height" in r["request_payload"] for r in push_rows)


@pytest.mark.asyncio
async def test_import_answers_batch_creates_integration_sync_logs(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "METSIGHTS_API_KEY", "test-key")
    await _ensure_test_engagement(test_db_session)

    uid = 5710
    await _seed_user(test_db_session, user_id=uid)
    pkg_id = 9710
    rid = "MS-IMPORT-LOG-01"

    test_db_session.add(
        AssessmentPackage(
            package_id=pkg_id,
            package_code="MET_IMPORT_LOG",
            display_name="Import Log Test",
            assessment_type_code="1",
            status="active",
        )
    )
    await test_db_session.flush()
    diet_cat_id = await _metsights_category_id(
        test_db_session, category_key="diet-lifestyle-parameters", fallback_category_id=5710
    )
    test_db_session.add(AssessmentPackageCategory(package_id=pkg_id, category_id=diet_cat_id))
    aid = 9711
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
    await test_db_session.commit()

    await _ensure_question_push_enabled(test_db_session, 6)

    diet_payload = {"living_region": "1", "diet_preference": "0"}

    async def _fake_get_sub(self, *, record_id: str, resource: str):
        resource = str(resource).strip().strip("/")
        if resource == "diet-lifestyle-parameters":
            return diet_payload
        return None

    async def _fake_options(self, *, record_id: str, resource: str):
        resource = str(resource).strip().strip("/")
        if resource == "diet-lifestyle-parameters":
            return {
                "living_region": {"choices": {"1": "Inland region", "0": "Coastal region"}},
                "diet_preference": {"choices": {"0": "Veg", "1": "Non-Veg"}},
            }
        return {}

    async def _fake_record_detail(self, *, record_id: str):
        return {"id": record_id, "vital_parameter": None, "physical_measurement": None}

    monkeypatch.setattr("modules.metsights.service.MetsightsService.get_record_subresource_or_none", _fake_get_sub)
    monkeypatch.setattr("modules.metsights.service.MetsightsService.options_record_subresource", _fake_options)
    monkeypatch.setattr("modules.metsights.service.MetsightsService.get_record_detail", _fake_record_detail)

    response = await async_client.post(
        f"/assessments/{aid}/metsights/import-answers-batch",
        headers=_user_auth_header(uid),
        json={
            "categories": [
                {"category": "diet-lifestyle-parameters", "category_of": "metsights", "reload": 1},
                {"category": "physical-measurement", "category_of": "metsights", "reload": 1},
                {"category": "vitals", "category_of": "metsights", "reload": 1},
            ]
        },
    )
    assert response.status_code == 200, response.text
    await test_db_session.commit()

    rows = (
        await test_db_session.execute(
            text(
                "SELECT api_endpoint_url, status, response_payload "
                "FROM integration_sync_logs WHERE provider = 'metsights' "
                "AND user_id = :uid ORDER BY sync_log_id"
            ),
            {"uid": uid},
        )
    ).mappings().all()

    assert len(rows) >= 1
    diet_row = next(r for r in rows if "diet-lifestyle-parameters" in r["api_endpoint_url"])
    assert diet_row["status"] == _SYNC_SUCCESS
    assert "imported" in diet_row["response_payload"]


@pytest.mark.asyncio
async def test_import_category_reload_zero_creates_skipped_sync_log(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "METSIGHTS_API_KEY", "test-key")
    await _ensure_test_engagement(test_db_session)

    uid = 5720
    await _seed_user(test_db_session, user_id=uid)
    pkg_id = 9720
    rid = "MS-SKIP-IMPORT-01"

    test_db_session.add(
        AssessmentPackage(
            package_id=pkg_id,
            package_code="MET_SKIP_IMPORT",
            display_name="Skip Import Test",
            assessment_type_code="2",
            status="active",
        )
    )
    await test_db_session.flush()
    phys_cat_id = await _metsights_category_id(
        test_db_session, category_key="physical-measurement", fallback_category_id=9721
    )
    test_db_session.add(AssessmentPackageCategory(package_id=pkg_id, category_id=phys_cat_id))
    aid = 9722
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
    test_db_session.add(
        QuestionnaireResponse(
            assessment_instance_id=aid,
            question_id=1,
            category_ids=[phys_cat_id],
            answer={"value": 170.0, "unit": "0"},
        )
    )
    await test_db_session.commit()

    await _ensure_category_questions_push_enabled(test_db_session, phys_cat_id)

    response = await async_client.post(
        f"/assessments/{aid}/metsights/import-answers",
        headers=_user_auth_header(uid),
        json={"category": "physical-measurement", "category_of": "metsights", "reload": 0},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "skipped"

    row = (
        await test_db_session.execute(
            text(
                "SELECT status, response_payload, api_endpoint_url "
                "FROM integration_sync_logs WHERE provider = 'metsights' "
                "AND user_id = :uid ORDER BY sync_log_id DESC LIMIT 1"
            ),
            {"uid": uid},
        )
    ).mappings().one()
    assert row["status"] == _SYNC_SKIPPED
    assert row["response_payload"]["skipped"] is True
    assert "physical-measurement" in row["api_endpoint_url"]


@pytest.mark.asyncio
async def test_submit_category_creates_integration_sync_logs(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "METSIGHTS_API_KEY", "test-key")
    await _ensure_test_engagement(test_db_session)

    uid = 5730
    await _seed_user(test_db_session, user_id=uid)
    pkg_id = 9730
    rid = "MS-SUBMIT-LEG-01"

    test_db_session.add(
        AssessmentPackage(
            package_id=pkg_id,
            package_code="MET_SUBMIT_LEG",
            display_name="Submit Legacy Test",
            assessment_type_code="1",
            status="active",
        )
    )
    await test_db_session.flush()
    phys_cat_id = await _metsights_category_id(
        test_db_session, category_key="physical-measurement", fallback_category_id=5730
    )
    test_db_session.add(AssessmentPackageCategory(package_id=pkg_id, category_id=phys_cat_id))
    aid = 9731
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
    test_db_session.add(
        QuestionnaireResponse(
            assessment_instance_id=aid,
            question_id=1,
            category_ids=[phys_cat_id],
            answer={"value": 180.0, "unit": "0"},
        )
    )
    test_db_session.add(
        QuestionnaireResponse(
            assessment_instance_id=aid,
            question_id=2,
            category_ids=[phys_cat_id],
            answer={"value": 72.0, "unit": "0"},
        )
    )
    await test_db_session.commit()

    await _ensure_category_questions_push_enabled(test_db_session, phys_cat_id)

    async def _fake_upsert(self, *, record_id: str, resource: str, body: dict):
        return {}

    async def _fake_options(self, *, record_id: str, resource: str):
        return {}

    monkeypatch.setattr("modules.metsights.service.MetsightsService.upsert_record_subresource", _fake_upsert)
    monkeypatch.setattr("modules.metsights.service.MetsightsService.options_record_subresource", _fake_options)

    response = await async_client.post(
        f"/assessments/{aid}/submit",
        headers=_user_auth_header(uid),
        json={"category": "physical-measurement", "category_of": "metsights"},
    )
    assert response.status_code == 200, response.text

    rows = (
        await test_db_session.execute(
            text(
                "SELECT status, api_endpoint_url, response_payload "
                "FROM integration_sync_logs WHERE provider = 'metsights' "
                "AND user_id = :uid AND status = :sync_success"
            ),
            {"uid": uid, "sync_success": _SYNC_SUCCESS},
        )
    ).mappings().all()

    assert any("/physical-measurement/" in r["api_endpoint_url"] for r in rows)
    assert any(r["response_payload"] == {"pushed": True} for r in rows)


@pytest.mark.asyncio
async def test_push_questionnaires_respects_selected_categories(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "METSIGHTS_API_KEY", "test-key")
    await _seed_employee(test_db_session, user_id=9721)
    await _seed_push_engagement(test_db_session, engagement_id=9721, package_id=9722)

    await _seed_user(test_db_session, user_id=5721)

    pushed_rid = "MS-PUSH-CAT-01"
    test_db_session.add(
        AssessmentInstance(
            assessment_instance_id=9723,
            user_id=5721,
            package_id=9722,
            engagement_id=9721,
            status="active",
            metsights_record_id=pushed_rid,
        )
    )
    # height -> physical-measurement; living_region -> diet-lifestyle-parameters
    test_db_session.add(
        QuestionnaireResponse(
            assessment_instance_id=9723,
            question_id=1,
            category_ids=[1],
            answer={"value": 175.0, "unit": "0"},
        )
    )
    test_db_session.add(
        QuestionnaireResponse(
            assessment_instance_id=9723,
            question_id=6,
            category_ids=[1],
            answer="1",
        )
    )
    await test_db_session.commit()

    upserted: list[str] = []

    async def _fake_upsert(self, *, record_id: str, resource: str, body: dict):
        upserted.append(resource)
        return {}

    async def _fake_options(self, *, record_id: str, resource: str):
        return {}

    monkeypatch.setattr("modules.metsights.service.MetsightsService.upsert_record_subresource", _fake_upsert)
    monkeypatch.setattr("modules.metsights.service.MetsightsService.options_record_subresource", _fake_options)

    response = await async_client.post(
        "/engagements/9721/push-questionnaires",
        headers=_employee_auth_header(9721),
        json={"package_id": 9722, "categories": ["physical-measurement"]},
    )
    assert response.status_code == 200, response.text
    assert upserted == ["physical-measurement"]


@pytest.mark.asyncio
async def test_push_questionnaires_rejects_unknown_categories(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "METSIGHTS_API_KEY", "test-key")
    await _seed_employee(test_db_session, user_id=9731)
    await _seed_push_engagement(test_db_session, engagement_id=9731, package_id=9732)

    response = await async_client.post(
        "/engagements/9731/push-questionnaires",
        headers=_employee_auth_header(9731),
        json={"package_id": 9732, "categories": ["not-a-real-category"]},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_push_questionnaires_rejects_empty_categories(async_client, test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "METSIGHTS_API_KEY", "test-key")
    await _seed_employee(test_db_session, user_id=9741)
    await _seed_push_engagement(test_db_session, engagement_id=9741, package_id=9742)

    response = await async_client.post(
        "/engagements/9741/push-questionnaires",
        headers=_employee_auth_header(9741),
        json={"package_id": 9742, "categories": []},
    )
    assert response.status_code == 422
