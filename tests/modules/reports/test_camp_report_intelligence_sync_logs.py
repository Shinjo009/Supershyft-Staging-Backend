"""Tests for integration_sync_logs on camp report intelligence enrich."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from modules.assessments.repository import AssessmentsRepository
from modules.audit.repository import AuditRepository
from modules.audit.service import AuditService
from modules.diagnostics.repository import DiagnosticsRepository
from modules.organizations.repository import OrganizationsRepository
from modules.reports.camp_report_intelligence import CAMP_INTELLIGENCE_INTERNAL_ENDPOINT
from modules.reports.camp_report_sections_repository import CampReportSectionsRepository
from modules.reports.camp_reports_repository import CampReportsRepository
from modules.reports.camp_reports_service import CampReportsService
from modules.reports.dependencies import get_reports_service
from tests.modules.questionnaire.test_questionnaire_user_routes import _seed_user
from tests.modules.reports.test_camp_report_intelligence_enrichment import sample_camp_report


def _camp_reports_service() -> CampReportsService:
    return CampReportsService(
        repository=CampReportsRepository(),
        sections_repository=CampReportSectionsRepository(),
        organizations_repository=OrganizationsRepository(),
        audit_service=AuditService(AuditRepository()),
        reports_service=get_reports_service(),
        assessments_repository=AssessmentsRepository(),
        diagnostics_repository=DiagnosticsRepository(),
    )


@pytest.mark.asyncio
async def test_apply_intelligence_creates_internal_integration_sync_log_on_success(
    test_db_session,
):
    await _seed_user(test_db_session, user_id=8801)
    service = _camp_reports_service()
    report = sample_camp_report()

    _, section_payload, _ = await service._apply_intelligence_to_section_with_sync_log(
        report=report,
        normalized_section="overall_risk_score",
        camp_section_key="overall_risk_score",
        camp_no=42,
        department=None,
        city=None,
        user_id=8801,
        source="enrich",
    )

    assert "intelligence" in section_payload

    result = await test_db_session.execute(
        text(
            "SELECT provider, user_id, api_endpoint_url, request_payload, "
            "response_payload, status, error_message "
            "FROM integration_sync_logs WHERE provider = 'internal' "
            "ORDER BY sync_log_id DESC LIMIT 1"
        )
    )
    row = result.mappings().one()
    assert row["provider"] == "internal"
    assert row["user_id"] == 8801
    assert row["api_endpoint_url"] == CAMP_INTELLIGENCE_INTERNAL_ENDPOINT
    assert row["request_payload"]["camp_no"] == 42
    assert row["request_payload"]["section"] == "overall_risk_score"
    assert row["request_payload"]["source"] == "enrich"
    assert row["status"] == "success"
    assert row["response_payload"] is not None
    assert row["error_message"] is None


@pytest.mark.asyncio
async def test_apply_intelligence_creates_internal_integration_sync_log_on_failure(
    test_db_session,
):
    await _seed_user(test_db_session, user_id=8802)
    service = _camp_reports_service()
    report = sample_camp_report()
    del report["overall_risk_score"]

    from core.exceptions import AppError

    with pytest.raises(AppError):
        await service._apply_intelligence_to_section_with_sync_log(
            report=report,
            normalized_section="overall_risk_score",
            camp_section_key="overall_risk_score",
            camp_no=42,
            department=None,
            city=None,
            user_id=8802,
            source="refresh",
        )

    result = await test_db_session.execute(
        text(
            "SELECT provider, request_payload, status, error_message "
            "FROM integration_sync_logs WHERE provider = 'internal' "
            "ORDER BY sync_log_id DESC LIMIT 1"
        )
    )
    row = result.mappings().one()
    assert row["provider"] == "internal"
    assert row["request_payload"]["source"] == "refresh"
    assert row["status"] == "failed"
    assert row["error_message"]
