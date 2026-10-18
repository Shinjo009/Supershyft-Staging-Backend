"""Business logic for engagement participant feedback."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from common.masking import mask_phone
from core.exceptions import AppError
from modules.engagements.engagement_feedback_repository import EngagementFeedbackRepository
from modules.engagements.engagement_feedback_schemas import (
    EngagementFeedbackAdminListItem,
    EngagementFeedbackPendingResponse,
    EngagementFeedbackResponse,
    EngagementFeedbackStatusResponse,
    EngagementFeedbackSubmitRequest,
)
from modules.engagements.feedback_category_keys import (
    category_keys_for_engagement_type_code,
    validate_category_ratings,
)
from modules.engagements.models import EngagementFeedback
from modules.engagement_types.repository import EngagementTypesRepository
from modules.engagements.repository import EngagementsRepository
from modules.employee.access_control import ensure_admin
from modules.employee.service import EmployeeContext


def _feedback_to_response(
    feedback: EngagementFeedback,
    *,
    engagement_id: int,
) -> EngagementFeedbackResponse:
    rating = feedback.overall_rating
    rating_value = rating.value if hasattr(rating, "value") else str(rating)
    return EngagementFeedbackResponse(
        feedback_id=feedback.feedback_id,
        engagement_participant_id=feedback.engagement_participant_id,
        engagement_id=engagement_id,
        overall_rating=rating_value,
        category_ratings=dict(feedback.category_ratings or {}),
        comment=feedback.comment,
        created_at=feedback.created_at,
    )


class EngagementFeedbackService:
    def __init__(
        self,
        *,
        feedback_repository: EngagementFeedbackRepository,
        engagements_repository: EngagementsRepository,
        engagement_types_repository: EngagementTypesRepository,
    ) -> None:
        self._feedback_repository = feedback_repository
        self._engagements_repository = engagements_repository
        self._engagement_types_repository = engagement_types_repository

    async def get_pending_for_user(
        self,
        db: AsyncSession,
        *,
        user_id: int,
    ) -> EngagementFeedbackPendingResponse:
        row = await self._feedback_repository.get_pending_enrollment_for_user(db, user_id=user_id)
        if row is None:
            return EngagementFeedbackPendingResponse(pending=False)
        _participant, engagement, type_code = row
        return EngagementFeedbackPendingResponse(
            pending=True,
            engagement_id=engagement.engagement_id,
            engagement_code=engagement.engagement_code,
            engagement_type_code=type_code,
            category_keys=category_keys_for_engagement_type_code(type_code),
        )

    async def get_for_user_engagement(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        engagement_id: int,
    ) -> EngagementFeedbackStatusResponse:
        participant = await self._engagements_repository.get_participant_for_user_engagement(
            db,
            user_id=user_id,
            engagement_id=engagement_id,
        )
        if participant is None:
            raise AppError(
                status_code=404,
                error_code="PARTICIPANT_NOT_FOUND",
                message="Participant does not exist",
            )
        feedback = await self._feedback_repository.get_by_participant_id(
            db,
            engagement_participant_id=participant.engagement_participant_id,
        )
        if feedback is None:
            return EngagementFeedbackStatusResponse(submitted=False, feedback=None)
        return EngagementFeedbackStatusResponse(
            submitted=True,
            feedback=_feedback_to_response(feedback, engagement_id=engagement_id),
        )

    async def submit_for_user_engagement(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        engagement_id: int,
        payload: EngagementFeedbackSubmitRequest,
    ) -> EngagementFeedbackResponse:
        participant = await self._engagements_repository.get_participant_for_user_engagement(
            db,
            user_id=user_id,
            engagement_id=engagement_id,
        )
        if participant is None:
            raise AppError(
                status_code=404,
                error_code="PARTICIPANT_NOT_FOUND",
                message="Participant does not exist",
            )
        existing = await self._feedback_repository.get_by_participant_id(
            db,
            engagement_participant_id=participant.engagement_participant_id,
        )
        if existing is not None:
            raise AppError(
                status_code=409,
                error_code="FEEDBACK_ALREADY_SUBMITTED",
                message="Feedback has already been submitted for this engagement",
            )

        engagement = await self._engagements_repository.get_engagement_by_id(db, engagement_id)
        type_code: str | None = None
        if engagement is not None and engagement.engagement_type is not None:
            type_row = await self._engagement_types_repository.get_by_id(db, engagement.engagement_type)
            type_code = type_row.code if type_row else None
        allowed_keys = category_keys_for_engagement_type_code(type_code)
        try:
            category_ratings = validate_category_ratings(
                payload.category_ratings,
                allowed_keys=allowed_keys,
            )
        except ValueError as exc:
            raise AppError(
                status_code=400,
                error_code="INVALID_INPUT",
                message=str(exc),
            ) from exc

        feedback = EngagementFeedback(
            engagement_participant_id=participant.engagement_participant_id,
            overall_rating=payload.overall_rating,
            category_ratings=category_ratings,
            comment=payload.comment,
        )
        db.add(feedback)
        await db.flush()
        await db.refresh(feedback)
        return _feedback_to_response(feedback, engagement_id=engagement_id)

    async def list_for_engagement_admin(
        self,
        db: AsyncSession,
        *,
        employee: EmployeeContext,
        engagement_id: int,
        page: int,
        limit: int,
    ) -> tuple[list[EngagementFeedbackAdminListItem], int]:
        ensure_admin(employee)
        engagement = await self._engagements_repository.get_engagement_by_id(db, engagement_id)
        if engagement is None:
            raise AppError(
                status_code=404,
                error_code="ENGAGEMENT_NOT_FOUND",
                message="Engagement does not exist",
            )
        rows, total = await self._feedback_repository.list_for_engagement(
            db,
            engagement_id=engagement_id,
            page=page,
            limit=limit,
        )
        items: list[EngagementFeedbackAdminListItem] = []
        for feedback, _participant, user in rows:
            rating = feedback.overall_rating
            rating_value = rating.value if hasattr(rating, "value") else str(rating)
            items.append(
                EngagementFeedbackAdminListItem(
                    feedback_id=feedback.feedback_id,
                    engagement_participant_id=feedback.engagement_participant_id,
                    user_id=user.user_id,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    phone=mask_phone(user.phone),
                    overall_rating=rating_value,
                    category_ratings=dict(feedback.category_ratings or {}),
                    comment=feedback.comment,
                    created_at=feedback.created_at,
                )
            )
        return items, total
