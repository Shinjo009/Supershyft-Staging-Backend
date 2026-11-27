"""Tests for camp booking_readiness on console engagement payloads."""

from __future__ import annotations

from datetime import date

import pytest

from modules.assessments.models import AssessmentPackage
from modules.diagnostics.models import DiagnosticPackage
from modules.engagements.models import BloodCollectionType, Engagement
from tests.helpers.auth import employee_auth_header, seed_employee
from tests.modules.engagements.test_console_routes import _ensure_assessment_package


def _auth_header(employee_id: int) -> dict[str, str]:
    return employee_auth_header(employee_id)


async def _ensure_diag_package(
    session,
    *,
    package_id: int,
    provider: str = "healthians",
    external_package_code: str = "PKG-EXT-1",
) -> None:
    existing = await session.get(DiagnosticPackage, package_id)
    if existing is None:
        session.add(
            DiagnosticPackage(
                diagnostic_package_id=package_id,
                reference_id=f"REF{package_id}",
                package_name=f"Diag {package_id}",
                diagnostic_provider=provider,
                external_package_code=external_package_code,
                status="active",
                bookings_count=0,
            )
        )
    else:
        existing.diagnostic_provider = provider
        existing.external_package_code = external_package_code


async def _seed_camp_engagement(
    session,
    *,
    engagement_id: int,
    engagement_code: str,
    **overrides,
) -> Engagement:
    await _ensure_assessment_package(session)
    default_diag_id = 88100 + (engagement_id % 100)
    diag_provider = overrides.pop("_diag_provider", "healthians")
    diag_external = overrides.pop("_diag_external_code", "DEAL-TEST")
    diag_id = overrides.get("diagnostic_package_id", default_diag_id)
    male_id = overrides.get("diagnostic_package_id_male")
    female_id = overrides.get("diagnostic_package_id_female")
    if male_id is not None:
        await _ensure_diag_package(session, package_id=male_id, provider=diag_provider, external_package_code=diag_external)
    if female_id is not None:
        await _ensure_diag_package(session, package_id=female_id, provider=diag_provider, external_package_code=diag_external)
    if diag_id is not None and male_id is None and female_id is None:
        await _ensure_diag_package(
            session,
            package_id=diag_id,
            provider=diag_provider,
            external_package_code=diag_external,
        )
    base = {
        "engagement_id": engagement_id,
        "engagement_name": f"Camp {engagement_id}",
        "engagement_code": engagement_code,
        "engagement_type": None,
        "assessment_package_id": 1,
        "diagnostic_package_id": diag_id,
        "status": "running",
        "start_date": date.today(),
        "end_date": date.today(),
        "blood_collection_type": BloodCollectionType.camp_collection,
        "external_camp_id": 9001,
        "latitude": 28.6,
        "longitude": 77.2,
        "pincode": "110001",
    }
    base.update(overrides)
    existing = await session.get(Engagement, engagement_id)
    if existing is not None:
        for key, value in base.items():
            setattr(existing, key, value)
        await session.flush()
        return existing
    eng = Engagement(**base)
    session.add(eng)
    await session.flush()
    return eng


def _codes(payload: dict) -> set[str]:
    return {issue["code"] for issue in payload["booking_readiness"]["issues"]}


@pytest.mark.asyncio
async def test_console_booking_readiness_ready_camp(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=820, role="admin", commit=False)
    await _ensure_diag_package(
        test_db_session,
        package_id=51,
        provider="healthians",
        external_package_code="2002",
    )
    await _seed_camp_engagement(
        test_db_session,
        engagement_id=88201,
        engagement_code="READY88201",
        diagnostic_package_id=51,
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/engagements/88201/console",
        headers=_auth_header(820),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    readiness = data["booking_readiness"]
    assert readiness["ready"] is True, readiness
    assert readiness["issues"] == []


@pytest.mark.asyncio
async def test_console_booking_readiness_home_collection_always_ready(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=821, role="admin", commit=False)
    await _seed_camp_engagement(
        test_db_session,
        engagement_id=88202,
        engagement_code="HOME88202",
        blood_collection_type=BloodCollectionType.home_collection,
        status="scheduled",
        diagnostic_package_id=None,
        external_camp_id=None,
        latitude=None,
        longitude=None,
        pincode=None,
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/engagements/88202/console",
        headers=_auth_header(821),
    )
    assert response.status_code == 200
    assert response.json()["data"]["booking_readiness"] == {"ready": True, "issues": []}


@pytest.mark.asyncio
async def test_console_booking_readiness_engagement_not_running(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=822, role="admin", commit=False)
    await _seed_camp_engagement(
        test_db_session,
        engagement_id=88203,
        engagement_code="SCH88203",
        status="scheduled",
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/engagements/88203/console",
        headers=_auth_header(822),
    )
    assert response.status_code == 200
    readiness = response.json()["data"]["booking_readiness"]
    assert readiness["ready"] is False
    assert "ENGAGEMENT_NOT_RUNNING" in _codes(response.json()["data"])


@pytest.mark.asyncio
async def test_console_booking_readiness_no_diagnostic_package(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=823, role="admin", commit=False)
    await _seed_camp_engagement(
        test_db_session,
        engagement_id=88204,
        engagement_code="NOPKG88204",
        diagnostic_package_id=None,
        diagnostic_package_id_male=None,
        diagnostic_package_id_female=None,
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/engagements/88204/console",
        headers=_auth_header(823),
    )
    assert response.status_code == 200
    assert "NO_DIAGNOSTIC_PACKAGE" in _codes(response.json()["data"])


@pytest.mark.asyncio
async def test_console_booking_readiness_split_package_incomplete(test_db_session):
    from modules.engagements.console.service import ConsoleService
    from modules.engagements.repository import EngagementsRepository

    await _ensure_diag_package(test_db_session, package_id=802)

    engagement = Engagement(
        engagement_id=8205,
        engagement_name="Split incomplete",
        engagement_code="SPLIT8205",
        engagement_type=None,
        assessment_package_id=1,
        diagnostic_package_id=None,
        diagnostic_package_id_male=802,
        diagnostic_package_id_female=None,
        status="running",
        start_date=date.today(),
        end_date=date.today(),
        blood_collection_type=BloodCollectionType.camp_collection,
        external_camp_id=9001,
        latitude=28.6,
        longitude=77.2,
        pincode="110001",
    )
    service = ConsoleService(EngagementsRepository())
    readiness = await service._camp_booking_readiness(test_db_session, engagement)
    codes = {issue["code"] for issue in readiness["issues"]}
    assert "SPLIT_PACKAGE_INCOMPLETE" in codes


@pytest.mark.asyncio
async def test_console_booking_readiness_external_camp_and_location(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=825, role="admin", commit=False)
    await _seed_camp_engagement(
        test_db_session,
        engagement_id=88206,
        engagement_code="LOC88206",
        external_camp_id=None,
        latitude=None,
        pincode="",
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/engagements/88206/console",
        headers=_auth_header(825),
    )
    assert response.status_code == 200
    codes = _codes(response.json()["data"])
    assert "EXTERNAL_CAMP_ID_MISSING" in codes
    assert "LOCATION_MISSING" in codes


@pytest.mark.asyncio
async def test_console_booking_readiness_package_provider_unsupported(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=826, role="admin", commit=False)
    await _seed_camp_engagement(
        test_db_session,
        engagement_id=88207,
        engagement_code="PKG88207",
        _diag_provider="HealthLabs",
        _diag_external_code="EXT803",
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/engagements/88207/console",
        headers=_auth_header(826),
    )
    assert response.status_code == 200
    assert "PACKAGE_PROVIDER_UNSUPPORTED" in _codes(response.json()["data"])


@pytest.mark.asyncio
async def test_console_booking_readiness_package_external_code_missing(async_client, test_db_session):
    await seed_employee(test_db_session, employee_id=827, role="admin", commit=False)
    await _seed_camp_engagement(
        test_db_session,
        engagement_id=88208,
        engagement_code="PKG88208",
        _diag_external_code="",
    )
    await test_db_session.commit()

    response = await async_client.get(
        "/engagements/88208/console",
        headers=_auth_header(827),
    )
    assert response.status_code == 200
    assert "PACKAGE_EXTERNAL_CODE_MISSING" in _codes(response.json()["data"])