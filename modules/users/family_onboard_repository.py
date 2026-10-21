"""Persistence queries for family onboard sessions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ColumnElement, delete, select
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

    async def delete_members_for_user_engagement(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        engagement_id: int,
    ) -> int:
        return await self._delete_members_then_empty_sessions(
            db,
            FamilyOnboardMember.user_id == user_id,
            FamilyOnboardMember.engagement_id == engagement_id,
        )

    async def delete_members_for_engagement(self, db: AsyncSession, *, engagement_id: int) -> int:
        return await self.delete_members_for_engagements(db, engagement_ids=[engagement_id])

    async def delete_members_for_engagements(
        self,
        db: AsyncSession,
        *,
        engagement_ids: list[int],
    ) -> int:
        if not engagement_ids:
            return 0
        return await self._delete_members_then_empty_sessions(
            db,
            FamilyOnboardMember.engagement_id.in_(engagement_ids),
        )

    async def delete_for_users(self, db: AsyncSession, *, user_ids: list[int]) -> None:
        """Remove family-onboard rows that would block user or participant deletes."""
        if not user_ids:
            return

        await db.execute(delete(FamilyOnboard).where(FamilyOnboard.booker_user_id.in_(user_ids)))
        await self._delete_members_then_empty_sessions(
            db,
            FamilyOnboardMember.user_id.in_(user_ids),
        )

    async def _delete_members_then_empty_sessions(
        self,
        db: AsyncSession,
        *filters: ColumnElement[bool],
    ) -> int:
        session_ids = list(
            (await db.execute(select(FamilyOnboardMember.family_onboard_id).where(*filters).distinct()))
            .scalars()
            .all()
        )
        result = await db.execute(delete(FamilyOnboardMember).where(*filters))
        if session_ids:
            remaining = select(FamilyOnboardMember.family_onboard_id).where(
                FamilyOnboardMember.family_onboard_id.in_(session_ids)
            )
            await db.execute(
                delete(FamilyOnboard).where(
                    FamilyOnboard.family_onboard_id.in_(session_ids),
                    ~FamilyOnboard.family_onboard_id.in_(remaining),
                )
            )
        return int(result.rowcount or 0)
