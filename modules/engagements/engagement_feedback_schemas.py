"""Pydantic schemas for engagement feedback APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from common.validation import OptionalSafeText
from modules.engagements.enums import EngagementFeedbackOverallRating

OverallRatingLiteral = Literal[
    "excellent",
    "very_good",
    "good",
    "could_be_better",
    "bad",
]


class EngagementFeedbackSubmitRequest(BaseModel):
    overall_rating: EngagementFeedbackOverallRating
    category_ratings: dict[str, int] = Field(default_factory=dict)
    comment: OptionalSafeText = None


class EngagementFeedbackResponse(BaseModel):
    feedback_id: int
    engagement_participant_id: int
    engagement_id: int
    overall_rating: OverallRatingLiteral
    category_ratings: dict[str, Any]
    comment: str | None
    created_at: datetime


class EngagementFeedbackPendingResponse(BaseModel):
    pending: bool
    engagement_id: int | None = None
    engagement_code: str | None = None
    engagement_type_code: str | None = None
    category_keys: list[str] | None = None


class EngagementFeedbackStatusResponse(BaseModel):
    submitted: bool
    feedback: EngagementFeedbackResponse | None = None


class EngagementFeedbackAdminListItem(BaseModel):
    feedback_id: int
    engagement_participant_id: int
    user_id: int
    first_name: str | None
    last_name: str | None
    phone: str | None
    overall_rating: OverallRatingLiteral
    category_ratings: dict[str, Any]
    comment: str | None
    created_at: datetime
