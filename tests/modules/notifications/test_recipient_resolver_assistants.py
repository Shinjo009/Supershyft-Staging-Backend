"""RecipientResolver assistant recipient types (phlebo / staff / expert)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from modules.notifications.recipient_resolver import RecipientResolver
from tests.helpers.auth import seed_employee, seed_partner


async def _seed_engagement(test_db_session, *, engagement_id: int = 9101) -> None:
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, status) "
            "VALUES (1, 'PKG1', 'Test Package', 1) ON CONFLICT (package_id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, package_name, diagnostic_provider, status) "
            "VALUES (1, 'Test Diagnostic', 'healthians', 1) ON CONFLICT (diagnostic_package_id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_types (code, display_name, is_active) "
            "VALUES ('bio_ai', 'BioAI', true) "
            "ON CONFLICT (code) DO UPDATE SET is_active = true"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO engagements "
            "(engagement_id, engagement_name, engagement_code, engagement_type, assessment_package_id, "
            "diagnostic_package_id, city, slot_duration, start_date, end_date, status) "
            "VALUES (:eid, 'Camp', 'ENG9101', "
            "(SELECT id FROM engagement_types WHERE code = 'bio_ai'), 1, 1, 'BLR', 20, "
            "'2026-06-01', '2026-06-30', 3) "
            "ON CONFLICT (engagement_id) DO NOTHING"
        ),
        {"eid": engagement_id},
    )


@pytest.mark.asyncio
async def test_resolve_assistants_staff_returns_assigned_employees(test_db_session):
    await _seed_engagement(test_db_session)
    await seed_partner(
        test_db_session,
        partner_id=501,
        role="phlebo",
        phone="5010000001",
        commit=False,
    )
    await seed_employee(
        test_db_session,
        employee_id=601,
        role="admin",
        phone="6010000001",
        commit=False,
    )
    await seed_employee(
        test_db_session,
        employee_id=602,
        role="inferior_admin",
        phone="6020000001",
        commit=False,
    )
    await test_db_session.execute(
        text(
            "INSERT INTO onboarding_assistant_assignment (partner_id, engagement_id) "
            "VALUES (501, 9101)"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO onboarding_assistant_assignment (employee_id, engagement_id) "
            "VALUES (601, 9101), (602, 9101)"
        )
    )
    await test_db_session.commit()

    resolver = RecipientResolver()
    staff = await resolver.resolve(
        test_db_session,
        recipient_type="assistants.staff",
        context={},
        engagement_id=9101,
    )
    staff_ids = sorted(
        c.get("employee_id") for c in staff.contacts if c.get("employee_id") is not None
    )
    assert staff_ids == [601, 602]
    assert all(c.get("partner_id") is None for c in staff.contacts)

    phlebo = await resolver.resolve(
        test_db_session,
        recipient_type="assistants.phlebo",
        context={},
        engagement_id=9101,
    )
    assert [c.get("partner_id") for c in phlebo.contacts] == [501]
