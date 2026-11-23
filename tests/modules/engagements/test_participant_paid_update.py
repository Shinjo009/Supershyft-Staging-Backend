from __future__ import annotations

import pytest
from sqlalchemy import text

from core.exceptions import AppError
from modules.audit.repository import AuditRepository
from modules.audit.service import AuditService
from modules.engagements.repository import EngagementsRepository
from modules.engagements.schemas import EngagementParticipantUpdateRequest
from modules.engagements.service import EngagementsService
from modules.employee.models import EmployeeRole
from modules.employee.service import EmployeeContext
from tests.helpers.auth import seed_employee


async def _seed_user(test_db_session, user_id: int) -> None:
    await test_db_session.execute(
        text(
            "INSERT INTO users (user_id, age, phone, status) "
            "VALUES (:uid, 30, :phone, 1) ON CONFLICT (user_id) DO NOTHING"
        ),
        {"uid": user_id, "phone": f"{user_id:010d}"},
    )


async def _seed_engagement(
    test_db_session, engagement_id: int, code: str, *, payment_type: str = "paid_by_group"
) -> None:
    type_id = (
        await test_db_session.execute(
            text("SELECT id FROM engagement_types WHERE code = 'bio_ai' LIMIT 1")
        )
    ).scalar_one()
    await test_db_session.execute(
        text(
            "INSERT INTO engagements ("
            "engagement_id, engagement_name, engagement_code, engagement_type, "
            "city, slot_duration, start_date, end_date, status, payment_type"
            ") VALUES ("
            ":eid, :ename, :ecode, :etype, 'BLR', 20, '2026-01-01', '2026-01-02', 3, :pt"
            ") ON CONFLICT (engagement_id) DO NOTHING"
        ),
        {
            "eid": engagement_id,
            "ename": code,
            "ecode": code,
            "etype": int(type_id),
            "pt": payment_type,
        },
    )


async def _seed_participant(test_db_session, *, ep_id: int, engagement_id: int, user_id: int) -> None:
    await _seed_user(test_db_session, user_id)
    await test_db_session.execute(
        text(
            "INSERT INTO engagement_participants "
            "(engagement_participant_id, engagement_id, user_id, booked_by_user_id, paid) "
            "VALUES (:ep, :eid, :uid, :uid, true) ON CONFLICT (engagement_participant_id) DO NOTHING"
        ),
        {"ep": ep_id, "eid": engagement_id, "uid": user_id},
    )


@pytest.mark.asyncio
async def test_update_participant_paid_toggles_for_paid_by_patient(test_db_session):
    await seed_employee(test_db_session, employee_id=42, role="admin")
    await _seed_engagement(test_db_session, 8830, "BK8830", payment_type="paid_by_patient")
    await _seed_participant(test_db_session, ep_id=88301, engagement_id=8830, user_id=8831)
    await test_db_session.commit()

    service = EngagementsService(
        EngagementsRepository(),
        audit_service=AuditService(AuditRepository()),
    )
    employee = EmployeeContext(employee_id=42, role=EmployeeRole.admin)

    res_false = await service.update_participant_for_employee(
        test_db_session,
        employee=employee,
        engagement_id=8830,
        user_id=8831,
        payload=EngagementParticipantUpdateRequest(paid=False),
        ip_address="127.0.0.1",
        user_agent="test",
        endpoint="/test",
    )
    assert res_false["paid"] is False

    persisted_paid = (
        await test_db_session.execute(
            text("SELECT paid FROM engagement_participants WHERE engagement_participant_id = 88301")
        )
    ).scalar_one()
    assert persisted_paid is False

    res_true = await service.update_participant_for_employee(
        test_db_session,
        employee=employee,
        engagement_id=8830,
        user_id=8831,
        payload=EngagementParticipantUpdateRequest(paid=True),
        ip_address="127.0.0.1",
        user_agent="test",
        endpoint="/test",
    )
    assert res_true["paid"] is True


@pytest.mark.asyncio
async def test_update_participant_paid_rejected_for_paid_by_group(test_db_session):
    await seed_employee(test_db_session, employee_id=42, role="admin")
    await _seed_engagement(test_db_session, 8831, "BK8831", payment_type="paid_by_group")
    await _seed_participant(test_db_session, ep_id=88311, engagement_id=8831, user_id=8832)
    await test_db_session.commit()

    service = EngagementsService(
        EngagementsRepository(),
        audit_service=AuditService(AuditRepository()),
    )
    employee = EmployeeContext(employee_id=42, role=EmployeeRole.admin)

    with pytest.raises(AppError) as exc:
        await service.update_participant_for_employee(
            test_db_session,
            employee=employee,
            engagement_id=8831,
            user_id=8832,
            payload=EngagementParticipantUpdateRequest(paid=False),
            ip_address="127.0.0.1",
            user_agent="test",
            endpoint="/test",
        )
    assert exc.value.status_code == 400
    assert exc.value.error_code == "PAID_UPDATE_NOT_ALLOWED"