"""Engagement domain enums (no SQLAlchemy / db.base dependency)."""

from __future__ import annotations

import enum


class EngagementKind(str, enum.Enum):
    """PostgreSQL enum `engagement_kind` / column `engagements.engagement_type`."""

    bio_ai = "bio_ai"
    blood_test = "blood_test"
    consultation = "consultation"
    blood_test_with_consultation = "blood_test_with_consultation"
    bio_ai_with_consultation = "bio_ai_with_consultation"


class BloodCollectionType(str, enum.Enum):
    """PostgreSQL enum `blood_collection_type_enum`."""

    home_collection = "home_collection"
    camp_collection = "camp_collection"


class ConsultationMode(str, enum.Enum):
    """PostgreSQL enum `consultation_mode_enum`."""

    online = "online"
    offline = "offline"


class EngagementStatus(str, enum.Enum):
    """Application-level engagement status values."""

    draft = "draft"
    scheduled = "scheduled"
    running = "running"
    completed = "completed"
    cancelled = "cancelled"
    published = "published"  # legacy rows only


class EngagementPaymentType(str, enum.Enum):
    """PostgreSQL enum `engagement_payment_type`."""

    paid_by_group = "paid_by_group"
    paid_by_patient = "paid_by_patient"


class EngagementFeedbackOverallRating(str, enum.Enum):
    """PostgreSQL enum `engagement_feedback_overall_rating`."""

    excellent = "excellent"
    very_good = "very_good"
    good = "good"
    could_be_better = "could_be_better"
    bad = "bad"


class UserOnboardingPayloadSection(str, enum.Enum):
    """PostgreSQL enum `user_onboarding_payload_section`."""

    personal_information = "personal_information"
    address = "address"
    schedule = "schedule"


class UserOnboardingPayloadInputType(str, enum.Enum):
    """PostgreSQL enum `user_onboarding_payload_input_type`."""

    number = "number"
    text = "text"
    json = "json"
