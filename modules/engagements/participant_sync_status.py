"""Derived Metsights sync flags for engagement participants (no DB columns)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.assessments.models import AssessmentInstance, AssessmentPackage
from modules.engagements.models import Engagement


def profile_created_on_metsights(metsights_profile_id: str | None) -> bool:
    return bool((metsights_profile_id or "").strip())


class EngagementSyncUserSets:
    """User IDs with primary / FitPrint Metsights record IDs for an engagement."""

    __slots__ = ("primary_record_synced_user_ids", "fitprint_record_synced_user_ids")

    def __init__(
        self,
        *,
        primary_record_synced_user_ids: set[int],
        fitprint_record_synced_user_ids: set[int],
    ) -> None:
        self.primary_record_synced_user_ids = primary_record_synced_user_ids
        self.fitprint_record_synced_user_ids = fitprint_record_synced_user_ids


async def load_engagement_sync_user_sets(
    db: AsyncSession,
    *,
    engagement: Engagement,
    user_ids: list[int],
) -> EngagementSyncUserSets:
    if not user_ids:
        return EngagementSyncUserSets(
            primary_record_synced_user_ids=set(),
            fitprint_record_synced_user_ids=set(),
        )

    primary_ids: set[int] = set()
    package_id = engagement.assessment_package_id
    if package_id is not None:
        rows = (
            await db.execute(
                select(AssessmentInstance.user_id)
                .where(AssessmentInstance.engagement_id == int(engagement.engagement_id))
                .where(AssessmentInstance.user_id.in_(user_ids))
                .where(AssessmentInstance.package_id == int(package_id))
                .where(AssessmentInstance.metsights_record_id.is_not(None))
                .where(AssessmentInstance.metsights_record_id != "")
            )
        ).all()
        primary_ids = {int(uid) for (uid,) in rows}

    fitprint_ids: set[int] = set()
    if bool(engagement.enroll_for_fitprint_full):
        rows = (
            await db.execute(
                select(AssessmentInstance.user_id)
                .join(AssessmentPackage, AssessmentPackage.package_id == AssessmentInstance.package_id)
                .where(AssessmentInstance.engagement_id == int(engagement.engagement_id))
                .where(AssessmentInstance.user_id.in_(user_ids))
                .where(AssessmentPackage.assessment_type_code == "7")
                .where(AssessmentInstance.metsights_record_id.is_not(None))
                .where(AssessmentInstance.metsights_record_id != "")
            )
        ).all()
        fitprint_ids = {int(uid) for (uid,) in rows}

    return EngagementSyncUserSets(
        primary_record_synced_user_ids=primary_ids,
        fitprint_record_synced_user_ids=fitprint_ids,
    )


def participant_sync_flags(
    *,
    user_id: int,
    metsights_profile_id: str | None,
    sync_sets: EngagementSyncUserSets,
) -> dict[str, bool]:
    return {
        "is_profile_created_on_metsights": profile_created_on_metsights(metsights_profile_id),
        "is_primary_record_id_synced": user_id in sync_sets.primary_record_synced_user_ids,
        "is_fitprint_record_id_synced": user_id in sync_sets.fitprint_record_synced_user_ids,
    }
