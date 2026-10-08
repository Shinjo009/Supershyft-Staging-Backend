"""Tests for reload-provider-blood-parameters participant endpoint."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

from modules.assessments.models import AssessmentInstance
from modules.engagements.models import Engagement, EngagementParticipant
from modules.reports.dependencies import get_reports_service
from modules.users.models import User
from tests.helpers.auth import employee_auth_header, seed_employee


def _auth_header(employee_id: int) -> dict[str, str]:
    return employee_auth_header(employee_id)


async def _engagement_type_id(test_db_session, code: str) -> int:
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_types (code, display_name, is_active) "
            "VALUES (:code, :dn, true) "
            "ON CONFLICT (code) DO UPDATE SET is_active = true"
        ),
        {"code": code, "dn": code},
    )
    await test_db_session.commit()
    row = (
        await test_db_session.execute(
            text("SELECT id FROM engagement_types WHERE code = :code"),
            {"code": code},
        )
    ).one()
    return int(row[0])


async def _seed_engagement(test_db_session, *, engagement_id: int, type_code: str):
    type_id = await _engagement_type_id(test_db_session, type_code)
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, status) "
            "VALUES (:pid, :pcode, :dname, 1) ON CONFLICT (package_id) DO NOTHING"
        ),
        {"pid": engagement_id, "pcode": f"PKG{engagement_id}", "dname": f"Package {engagement_id}"},
    )
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, reference_id, package_name, diagnostic_provider, status, bookings_count) "
            "VALUES (:did, :ref, :pname, 'healthians', 1, 0) ON CONFLICT (diagnostic_package_id) DO NOTHING"
        ),
        {"did": engagement_id, "ref": f"REF{engagement_id}", "pname": f"Diag {engagement_id}"},
    )
    test_db_session.add(
        Engagement(
            engagement_id=engagement_id,
            engagement_code=f"ENG{engagement_id}",
            engagement_type=type_id,
            assessment_package_id=engagement_id,
            diagnostic_package_id=engagement_id,
            slot_duration=20,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            status="running",
        )
    )
    await test_db_session.commit()


@pytest.mark.asyncio
async def test_reload_provider_blood_parameters_requires_auth(async_client):
    response = await async_client.post(
        "/engagements/1/participants/reload-provider-blood-parameters",
        json={"user_ids": [1]},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_reload_provider_blood_parameters_rejects_unknown_participants(async_client, test_db_session):
    engagement_id = 88301
    admin_id = 88301
    await seed_employee(test_db_session, employee_id=admin_id)
    await _seed_engagement(test_db_session, engagement_id=engagement_id, type_code="reload_blood_reject")

    response = await async_client.post(
        f"/engagements/{engagement_id}/participants/reload-provider-blood-parameters",
        headers=_auth_header(admin_id),
        json={"user_ids": [99988301]},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reload_provider_blood_parameters_calls_reports_with_reload(
    async_client,
    fastapi_app,
    test_db_session,
    monkeypatch,
):
    engagement_id = 88302
    admin_id = 88302
    participant_id = 88303
    await seed_employee(test_db_session, employee_id=admin_id)
    await _seed_engagement(test_db_session, engagement_id=engagement_id, type_code="reload_blood_ok")
    test_db_session.add(
        User(
            user_id=participant_id,
            age=30,
            phone=f"{participant_id:010d}",
            status="active",
            first_name="Danny",
            last_name="Test",
        )
    )
    await test_db_session.flush()
    test_db_session.add(
        EngagementParticipant(
            engagement_participant_id=88302,
            engagement_id=engagement_id,
            user_id=participant_id,
            booked_by_user_id=participant_id,
        )
    )
    test_db_session.add(
        AssessmentInstance(
            assessment_instance_id=88302,
            user_id=participant_id,
            engagement_id=engagement_id,
            package_id=engagement_id,
            status="active",
            metsights_record_id="019ff02b-61cb-c3ef-fb11-4ac26a8e42f4",
        )
    )
    await test_db_session.commit()

    captured: dict = {}

    async def _fake_get_blood_parameters_for_user(db, **kwargs):
        captured.update(kwargs)
        return []

    mock_reports = MagicMock()
    mock_reports.get_blood_parameters_for_user = AsyncMock(side_effect=_fake_get_blood_parameters_for_user)
    fastapi_app.dependency_overrides[get_reports_service] = lambda: mock_reports

    monkeypatch.setattr(
        "modules.reports.blood_booking_reports.get_current_report_root",
        AsyncMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        "modules.reports.blood_parameters_schemas.has_usable_provider_blood_parameters",
        lambda _blob: True,
    )

    response = await async_client.post(
        f"/engagements/{engagement_id}/participants/reload-provider-blood-parameters",
        headers=_auth_header(admin_id),
        json={"user_ids": [participant_id]},
    )

    fastapi_app.dependency_overrides.pop(get_reports_service, None)

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["reloaded"] == 1
    assert body["skipped"] == 0
    assert body["failed"] == 0
    assert captured.get("reload") == 1
    assert captured.get("load_from") == "provider"
    assert captured.get("user_id") == participant_id
    assert captured.get("assessment_id") == 88302
