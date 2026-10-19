"""Persistence queries for family onboard sessions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from modules.users.models import FamilyOnboard, FamilyOnboardMember


class FamilyOnboardRepository:
    async def create_session(
        self,
        db: AsyncSession,
        *,
        family_onboard_id: str,
        booker_user_id: int,
        discount_code: str | None,
        expires_at: datetime,
        members: list[dict],
    ) -> FamilyOnboard:
        row = FamilyOnboard(
            family_onboard_id=family_onboard_id,
            booker_user_id=booker_user_id,
            status="pending_payment",
            discount_code=(discount_code or "").strip() or None,
            expires_at=expires_at,
        )
        db.add(row)
        await db.flush()
        for member in members:
            db.add(
                FamilyOnboardMember(
                    family_onboard_id=family_onboard_id,
                    user_id=int(member["user_id"]),
                    engagement_id=int(member["engagement_id"]),
                    engagement_participant_id=int(member["engagement_participant_id"]),
                )
            )
        await db.flush()
        return row

    async def get_session_with_members(
        self,
        db: AsyncSession,
        family_onboard_id: str,
    ) -> FamilyOnboard | None:
        result = await db.execute(
            select(FamilyOnboard)
            .where(FamilyOnboard.family_onboard_id == family_onboard_id)
            .options(selectinload(FamilyOnboard.members))
        )
        return result.scalar_one_or_none()
