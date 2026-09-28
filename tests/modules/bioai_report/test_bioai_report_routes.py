"""Integration tests for GET /bioai-report/{assessment_instance_id}."""

from __future__ import annotations

from datetime import date, timedelta
import inspect

import pytest
from sqlalchemy import text

from modules.assessments.models import AssessmentInstance
from modules.bioai_report.report_engine.api.dependencies import get_bioreport_service
from modules.bioai_report.report_engine.api import router as bioai_router
from modules.bioai_report.report_engine.models.report import (
    BioReport,
    ExecutiveSummary,
    PatientInfo,
    ReportMetadata,
)
from modules.engagements.models import Engagement
from modules.users.models import User


class _FakeBioReportService:
    async def generate_for_assessment_instance(self, *, assessment_instance_id: int, db):
        return BioReport(
            patient=PatientInfo(record_id="REC-1", name="Test User"),
            executive_summary=ExecutiveSummary(patient=PatientInfo(record_id="REC-1", name="Test User")),
            disease_sections=[],
            report_metadata=ReportMetadata(
                record_id="REC-1",
                engine_version="test",
                template_version="test",
            ),
        )


async def _seed_assessment(test_db_session, *, assessment_id: int, user_id: int):
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, package_name, diagnostic_provider, status) "
            "VALUES (1, 'Test Diagnostic', 'test_provider', 'active') ON CONFLICT (diagnostic_package_id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, assessment_type_code, status) "
            "VALUES (1, 'PRO', 'Pro', '2', 'active') "
            "ON CONFLICT (package_id) DO UPDATE SET assessment_type_code = EXCLUDED.assessment_type_code"
        )
    )
    test_db_session.add(
        User(
            user_id=user_id,
            first_name="Test",
            last_name="User",
            phone=f"{user_id}000000",
            age=30,
            status="active",
        )
    )
    test_db_session.add(
        Engagement(
            engagement_id=assessment_id,
            engagement_name="BioAI Route Engagement",
            engagement_code=f"ENG-BIOAI-ROUTE-{assessment_id}",
            engagement_type="bio_ai",
            assessment_package_id=1,
            diagnostic_package_id=1,
            city="Bengaluru",
            slot_duration=20,
            start_date=date.today() - timedelta(days=7),
            end_date=date.today() + timedelta(days=7),
            status="running",
        )
    )
    test_db_session.add(
        AssessmentInstance(
            assessment_instance_id=assessment_id,
            user_id=user_id,
            package_id=1,
            engagement_id=assessment_id,
            status="completed",
            metsights_record_id="REC-1",
        )
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_get_bioreport_returns_engine_content_without_endpoint_auth(
    async_client, fastapi_app, test_db_session
):
    await _seed_assessment(test_db_session, assessment_id=99501, user_id=89501)
    fastapi_app.dependency_overrides[get_bioreport_service] = lambda: _FakeBioReportService()

    response = await async_client.get("/bioai-report/99501")

    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"patient", "executive_summary", "disease_sections", "report_metadata", "health_trends"}
    assert body["patient"]["record_id"] == "REC-1"
    fastapi_app.dependency_overrides.pop(get_bioreport_service, None)


def test_bioai_route_does_not_query_employee_or_custom_auth():
    source = inspect.getsource(bioai_router)
    assert "employee" not in source.lower()
    assert "get_current_employee" not in source
    assert "ensure_internal_employee" not in source
    assert "phone" not in source.lower()
