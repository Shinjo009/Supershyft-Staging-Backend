"""Access tests for GET /bioai-report/{assessment_instance_id}."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from core.dependencies import get_optional_user
from core.exceptions import add_exception_handlers
from db.session import get_db
from modules.bioai_report.report_engine.api.dependencies import (
    get_bioai_trend_service,
    get_bioreport_service,
)
from modules.bioai_report.report_engine.api.router import router
from modules.bioai_report.report_engine.models.report import (
    BioReport,
    ExecutiveSummary,
    PatientInfo,
    ReportMetadata,
)
from modules.employee.dependencies import get_optional_employee
from modules.employee.models import EmployeeRole
from modules.employee.service import EmployeeContext


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


class _FakeTrendService:
    async def embed_for_assessment_instance(self, db, *, assessment_instance_id, report_payload):
        return {"series": []}


async def _noop_db():
    yield SimpleNamespace()


def _app(*, user=None, employee=None) -> FastAPI:
    app = FastAPI()
    add_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_db] = _noop_db
    app.dependency_overrides[get_optional_user] = lambda: user
    app.dependency_overrides[get_optional_employee] = lambda: employee
    app.dependency_overrides[get_bioreport_service] = lambda: _FakeBioReportService()
    app.dependency_overrides[get_bioai_trend_service] = lambda: _FakeTrendService()
    return app


@pytest.fixture
def owner_instance(monkeypatch):
    async def _get_instance(self, db, assessment_instance_id: int):
        if int(assessment_instance_id) != 99501:
            return None
        return SimpleNamespace(user_id=89501, assessment_instance_id=99501)

    monkeypatch.setattr(
        "modules.assessments.repository.AssessmentsRepository.get_instance_by_id",
        _get_instance,
    )


async def _get(app: FastAPI, path: str = "/bioai-report/99501"):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


@pytest.mark.asyncio
async def test_get_bioreport_requires_auth(owner_instance):
    response = await _get(_app())
    assert response.status_code == 401
    assert response.json() == {"error_code": "AUTH_FAILED", "message": "Authentication failed"}


@pytest.mark.asyncio
async def test_get_bioreport_owner_can_read(owner_instance):
    response = await _get(_app(user=SimpleNamespace(user_id=89501)))
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {
        "patient",
        "executive_summary",
        "disease_sections",
        "report_metadata",
        "health_trends",
    }
    assert body["patient"]["record_id"] == "REC-1"


@pytest.mark.asyncio
async def test_get_bioreport_other_user_cannot_read(owner_instance):
    response = await _get(_app(user=SimpleNamespace(user_id=89503)))
    assert response.status_code == 404
    assert response.json() == {
        "error_code": "ASSESSMENT_NOT_FOUND",
        "message": "Assessment does not exist",
    }


@pytest.mark.asyncio
async def test_get_bioreport_admin_can_read_any_instance(owner_instance):
    admin = EmployeeContext(employee_id=99514, role=EmployeeRole.admin)
    response = await _get(_app(employee=admin))
    assert response.status_code == 200
    assert response.json()["patient"]["record_id"] == "REC-1"


@pytest.mark.asyncio
async def test_get_bioreport_non_admin_employee_is_forbidden(owner_instance):
    manager = EmployeeContext(employee_id=99515, role=EmployeeRole.organization_manager)
    response = await _get(_app(employee=manager))
    assert response.status_code == 403
    assert response.json()["error_code"] == "FORBIDDEN"
