"""Shared fixtures for notification module tests."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from modules.engagements.models import Engagement
from tests.helpers.engagement_types import engagement_type_id


async def seed_notification_test_engagement(
    session: AsyncSession,
    *,
    engagement_id: int,
    engagement_code: str,
) -> None:
    type_id = await engagement_type_id(session, "bio_ai")
    session.add(
        Engagement(
            engagement_id=engagement_id,
            engagement_name="Camp",
            engagement_code=engagement_code,
            engagement_type=type_id,
            assessment_package_id=1,
            diagnostic_package_id=1,
            city="BLR",
            slot_duration=20,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            status="running",
        )
    )
    await session.commit()
