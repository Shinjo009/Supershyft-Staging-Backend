"""Repository for engagement participant feedback."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from modules.engagements.models import (
    Engagement,
    EngagementFeedback,
    EngagementParticipant,
    EngagementType,
)
from modules.users.models import User


class EngagementFeedbackRepository:
    async def get_by_participant_id(
        self,
        db: AsyncSession,
        *,
        engagement_participant_id: int,
    ) -> EngagementFeedback | None:
        result = await db.execute(
            select(EngagementFeedback).where(
                EngagementFeedback.engagement_participant_id == engagement_participant_id
            )
        )
        return result.scalar_one_or_none()

    async def get_pending_enrollment_for_user(
        self,
        db: AsyncSession,
        *,
        user_id: int,
    ) -> tuple[EngagementParticipant, Engagement, str | None] | None:
        result = await db.execute(
            select(EngagementParticipant, Engagement, EngagementType.code)
            .join(Engagement, Engagement.engagement_id == EngagementParticipant.engagement_id)
            .outerjoin(EngagementType, EngagementType.id == Engagement.engagement_type)
            .outerjoin(
                EngagementFeedback,
                EngagementFeedback.engagement_participant_id
                == EngagementParticipant.engagement_participant_id,
            )
            .where(EngagementParticipant.user_id == user_id)
            .where(EngagementFeedback.feedback_id.is_(None))
            .order_by(EngagementParticipant.engagement_participant_id.desc())
            .limit(1)
        )
        row = result.one_or_none()
        if row is None:
            return None
        participant, engagement, type_code = row
        return participant, engagement, type_code

    async def list_for_engagement(
        self,
        db: AsyncSession,
        *,
        engagement_id: int,
        page: int,
        limit: int,
    ) -> tuple[list[tuple[EngagementFeedback, EngagementParticipant, User]], int]:
        base = (
            select(EngagementFeedback, EngagementParticipant, User)
            .join(
                EngagementParticipant,
                EngagementParticipant.engagement_participant_id
                == EngagementFeedback.engagement_participant_id,
            )
            .join(User, User.user_id == EngagementParticipant.user_id)
            .where(EngagementParticipant.engagement_id == engagement_id)
        )
        count_result = await db.execute(
            select(func.count(EngagementFeedback.feedback_id))
            .select_from(EngagementFeedback)
            .join(
                EngagementParticipant,
                EngagementParticipant.engagement_participant_id
                == EngagementFeedback.engagement_participant_id,
            )
            .where(EngagementParticipant.engagement_id == engagement_id)
        )
        total = int(count_result.scalar_one())

        offset = (page - 1) * limit
        result = await db.execute(
            base.order_by(EngagementFeedback.created_at.desc(), EngagementFeedback.feedback_id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.all()), total
