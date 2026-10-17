"""Clear report URL or values for one participant (admin)."""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.assessments.models import AssessmentInstance, AssessmentPackage
from modules.engagements.models import ParticipantBloodBooking
from modules.reports.models import IndividualHealthReport

ClinicalProduct = Literal["blood", "bio_ai", "fitprint"]
ClinicalField = Literal["report_url", "values"]

_METSIGHTS_PRO_BASIC_TYPE_CODES = ("1", "2")


async def clear_participant_clinical_data(
    db: AsyncSession,
    *,
    engagement_id: int,
    engagement_participant_id: int,
    user_id: int,
    product: ClinicalProduct,
    field: ClinicalField,
) -> int:
    """Null out the requested field. Returns number of rows updated."""
    if product == "blood":
        result = await db.execute(
            select(ParticipantBloodBooking).where(
                ParticipantBloodBooking.engagement_participant_id == engagement_participant_id
            )
        )
        rows = list(result.scalars().all())
        updated = 0
        for row in rows:
            if field == "report_url":
                if row.diagnostic_report_url is not None:
                    row.diagnostic_report_url = None
                    updated += 1
            else:
                changed = False
                if row.blood_parameters is not None:
                    row.blood_parameters = None
                    changed = True
                if row.blood_report_raw is not None:
                    row.blood_report_raw = None
                    changed = True
                if row.blood_parameters_full_report is not None:
                    row.blood_parameters_full_report = None
                    changed = True
                if row.blood_parameters_verified_at is not None:
                    row.blood_parameters_verified_at = None
                    changed = True
                if changed:
                    updated += 1
            db.add(row)
        if updated:
            await db.flush()
        return updated

    type_codes = _METSIGHTS_PRO_BASIC_TYPE_CODES if product == "bio_ai" else ("7",)
    ihr_result = await db.execute(
        select(IndividualHealthReport)
        .join(
            AssessmentInstance,
            AssessmentInstance.assessment_instance_id == IndividualHealthReport.assessment_instance_id,
        )
        .join(
            AssessmentPackage,
            AssessmentPackage.package_id == AssessmentInstance.package_id,
        )
        .where(
            IndividualHealthReport.engagement_id == engagement_id,
            IndividualHealthReport.user_id == user_id,
            AssessmentPackage.assessment_type_code.in_(type_codes),
        )
    )
    ihr_rows = list(ihr_result.scalars().all())
    updated = 0
    for ihr in ihr_rows:
        if field == "report_url":
            if ihr.report_url is not None:
                ihr.report_url = None
                updated += 1
        elif ihr.reports is not None:
            ihr.reports = None
            updated += 1
        db.add(ihr)
    if updated:
        await db.flush()
    return updated
