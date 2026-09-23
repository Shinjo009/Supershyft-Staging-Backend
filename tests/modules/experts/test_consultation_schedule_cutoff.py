"""Service wiring tests for schedule cutoff on consultation reschedule/cancel."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from common.schedule_cutoff import MSG_CONSULTATION_CANCEL, MSG_CONSULTATION_RESCHEDULE
from core.exceptions import AppError
from modules.experts.schemas import ConsultationCancelRequest, ConsultationRescheduleRequest
from modules.experts.service import ExpertAvailabilityService
from modules.experts.repository import (
    ExpertAvailabilityOverrideRepository,
    ExpertAvailabilityRepository,
    ExpertsRepository,
)
from tests.modules.experts.test_consultation_reschedule import _seed_reschedule_fixture

_IST = ZoneInfo("Asia/Kolkata")
_FIXED_NOW = datetime(2026, 9, 23, 21, 0, tzinfo=_IST)


@pytest.fixture(autouse=True)
def _freeze_cutoff_clock(monkeypatch):
    """Do not bypass the gate; freeze IST 'now' for deterministic remaining-hours checks."""
    import common.schedule_cutoff as sc

    def _gated(appointment_date, appointment_slot, *, message, now=None, min_lead=sc.DEFAULT_MIN_LEAD):
        return sc.ensure_schedule_change_allowed(
            appointment_date,
            appointment_slot,
            message=message,
            now=_FIXED_NOW,
            min_lead=min_lead,
        )

    monkeypatch.setattr("modules.experts.service.ensure_schedule_change_allowed", _gated)


def _service() -> ExpertAvailabilityService:
    return ExpertAvailabilityService(
        experts_repository=ExpertsRepository(),
        availability_repository=ExpertAvailabilityRepository(),
        override_repository=ExpertAvailabilityOverrideRepository(),
    )


@pytest.mark.asyncio
async def test_consultation_reschedule_blocked_within_12h(test_db_session):
    await _seed_reschedule_fixture(
        test_db_session,
        engagement_id=91001,
        participant_user_id=91001,
        participant_id=91001,
        consultation_date=date(2026, 9, 24),
        consultation_slot="07:00",
        start_date=date(2026, 9, 20),
        end_date=date(2026, 9, 30),
    )
    await test_db_session.commit()

    with pytest.raises(AppError) as exc:
        await _service().reschedule_consultation_slot(
            test_db_session,
            user_id=91001,
            payload=ConsultationRescheduleRequest(
                engagement_id=91001,
                consultation_date=date(2026, 9, 25),
                consultation_slot="10:00",
                expert_type="nutritionist",
            ),
        )
    assert exc.value.error_code == "SCHEDULE_CHANGE_CUTOFF"
    assert exc.value.message == MSG_CONSULTATION_RESCHEDULE


@pytest.mark.asyncio
async def test_consultation_reschedule_allowed_with_17h_remaining(test_db_session, monkeypatch):
    await _seed_reschedule_fixture(
        test_db_session,
        engagement_id=91002,
        participant_user_id=91002,
        participant_id=91002,
        consultation_date=date(2026, 9, 24),
        consultation_slot="14:00",
        start_date=date(2026, 9, 20),
        end_date=date(2026, 9, 30),
    )
    await test_db_session.commit()

    service = _service()
    monkeypatch.setattr(service, "_slot_is_available", AsyncMock(return_value=True))

    result = await service.reschedule_consultation_slot(
        test_db_session,
        user_id=91002,
        payload=ConsultationRescheduleRequest(
            engagement_id=91002,
            consultation_date=date(2026, 9, 25),
            consultation_slot="10:00",
            expert_type="nutritionist",
        ),
    )
    assert result["message"] == "Consultation rescheduled"
    assert result["date"] == "2026-09-25"


@pytest.mark.asyncio
async def test_consultation_cancel_blocked_past_date(test_db_session):
    await _seed_reschedule_fixture(
        test_db_session,
        engagement_id=91003,
        participant_user_id=91003,
        participant_id=91003,
        consultation_date=date(2026, 9, 22),
        consultation_slot="10:00",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
    )
    await test_db_session.commit()

    with pytest.raises(AppError) as exc:
        await _service().cancel_consultation(
            test_db_session,
            user_id=91003,
            payload=ConsultationCancelRequest(engagement_id=91003, expert_type="nutritionist"),
        )
    assert exc.value.error_code == "SCHEDULE_CHANGE_CUTOFF"
    assert exc.value.message == MSG_CONSULTATION_CANCEL


@pytest.mark.asyncio
async def test_consultation_cancel_allowed_with_17h_remaining(test_db_session):
    await _seed_reschedule_fixture(
        test_db_session,
        engagement_id=91004,
        participant_user_id=91004,
        participant_id=91004,
        consultation_date=date(2026, 9, 24),
        consultation_slot="14:00",
        start_date=date(2026, 9, 20),
        end_date=date(2026, 9, 30),
    )
    await test_db_session.commit()

    result = await _service().cancel_consultation(
        test_db_session,
        user_id=91004,
        payload=ConsultationCancelRequest(engagement_id=91004, expert_type="nutritionist"),
    )
    assert result["message"] == "Consultation cancelled"
    assert result["deleted_count"] == 1
