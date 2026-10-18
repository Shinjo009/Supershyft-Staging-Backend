"""Repository for camp consultation request OTP contexts."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.experts.models import CampConsultationRequestOtpContext


class CampConsultationRequestOtpRepository:
    async def create(
        self,
        db: AsyncSession,
        context: CampConsultationRequestOtpContext,
    ) -> CampConsultationRequestOtpContext:
        db.add(context)
        await db.flush()
        return context

    async def get_by_session_id(
        self,
        db: AsyncSession,
        *,
        auth_otp_session_id: int,
    ) -> CampConsultationRequestOtpContext | None:
        result = await db.execute(
            select(CampConsultationRequestOtpContext).where(
                CampConsultationRequestOtpContext.auth_otp_session_id == auth_otp_session_id
            )
        )
        return result.scalar_one_or_none()

    async def get_active_for_verify(
        self,
        db: AsyncSession,
        *,
        engagement_id: int,
        engagement_participant_id: int,
        auth_otp_session_id: int,
        initiated_by_partner_id: int | None,
        initiated_by_employee_id: int | None,
    ) -> CampConsultationRequestOtpContext | None:
        query = (
            select(CampConsultationRequestOtpContext)
            .where(CampConsultationRequestOtpContext.engagement_id == engagement_id)
            .where(CampConsultationRequestOtpContext.engagement_participant_id == engagement_participant_id)
            .where(CampConsultationRequestOtpContext.auth_otp_session_id == auth_otp_session_id)
            .where(CampConsultationRequestOtpContext.consumed_at.is_(None))
        )
        if initiated_by_partner_id is not None:
            query = query.where(
                CampConsultationRequestOtpContext.initiated_by_partner_id == initiated_by_partner_id
            )
        elif initiated_by_employee_id is not None:
            query = query.where(
                CampConsultationRequestOtpContext.initiated_by_employee_id == initiated_by_employee_id
            )
        result = await db.execute(query.limit(1))
        return result.scalar_one_or_none()

    async def mark_consumed(self, db: AsyncSession, context_id: int) -> None:
        await db.execute(
            update(CampConsultationRequestOtpContext)
            .where(CampConsultationRequestOtpContext.id == context_id)
            .values(consumed_at=datetime.now(timezone.utc))
        )
