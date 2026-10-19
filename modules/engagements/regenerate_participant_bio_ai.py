"""Admin: refresh MetSights Bio AI JSON and regenerate PDF at the existing slug."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppError
from modules.assessments.models import AssessmentInstance, AssessmentPackage
from modules.bioai_report.pdf_registration import (
    is_bio_ai_assessment_type,
    is_bio_ai_reports_permanent_url,
    regenerate_permanent_bio_ai_report_url,
    resolve_canonical_bio_ai_report_url,
)
from modules.engagements.models import Engagement
from modules.metsights.service import MetsightsService
from modules.notifications.load_bioai_reports import _fetch_metsights_report_json
from modules.reports.models import IndividualHealthReport

_METSIGHTS_PRO_BASIC_TYPE_CODES = ("1", "2")


async def regenerate_participant_bio_ai_report(
    db: AsyncSession,
    *,
    metsights_service: MetsightsService,
    engagement_id: int,
    user_id: int,
) -> dict[str, Any]:
    """Fetch latest MetSights report JSON for this camp instance and regenerate the PDF."""
    engagement = await db.get(Engagement, int(engagement_id))
    if engagement is None:
        raise AppError(
            status_code=404,
            error_code="ENGAGEMENT_NOT_FOUND",
            message="Engagement does not exist",
        )

    query = (
        select(AssessmentInstance, AssessmentPackage, IndividualHealthReport)
        .join(AssessmentPackage, AssessmentPackage.package_id == AssessmentInstance.package_id)
        .join(
            IndividualHealthReport,
            IndividualHealthReport.assessment_instance_id
            == AssessmentInstance.assessment_instance_id,
        )
        .where(
            AssessmentInstance.engagement_id == int(engagement_id),
            AssessmentInstance.user_id == int(user_id),
            AssessmentPackage.assessment_type_code.in_(_METSIGHTS_PRO_BASIC_TYPE_CODES),
        )
    )
    primary_package_id = getattr(engagement, "assessment_package_id", None)
    if primary_package_id is not None:
        query = query.where(AssessmentInstance.package_id == int(primary_package_id))

    result = await db.execute(query.order_by(AssessmentInstance.assessment_instance_id.desc()).limit(1))
    row = result.first()
    if row is None:
        raise AppError(
            status_code=404,
            error_code="ASSESSMENT_NOT_FOUND",
            message="Bio AI assessment instance not found for this participant",
        )

    instance, package, ihr = row
    instance_id = int(instance.assessment_instance_id)
    record_id = (instance.metsights_record_id or "").strip()
    type_code = (package.assessment_type_code or "").strip()

    if not record_id:
        raise AppError(
            status_code=422,
            error_code="INVALID_STATE",
            message="Participant has no MetSights record id for Bio AI",
        )
    if not is_bio_ai_assessment_type(type_code):
        raise AppError(
            status_code=422,
            error_code="INVALID_STATE",
            message="Assessment is not a Bio AI type",
        )

    stored_url = (ihr.report_url or "").strip()
    canonical_url = await resolve_canonical_bio_ai_report_url(
        db,
        user_id=int(user_id),
        engagement_id=int(engagement_id),
        assessment_instance_id=instance_id,
        report_url=stored_url or None,
    )
    report_url = (canonical_url or stored_url).strip()
    if not is_bio_ai_reports_permanent_url(report_url):
        raise AppError(
            status_code=422,
            error_code="INVALID_STATE",
            message="Participant does not have a permanent bio-ai-reports URL to regenerate",
        )

    fetched_reports, _record_incomplete = await _fetch_metsights_report_json(
        db,
        metsights_service=metsights_service,
        record_id=record_id,
        type_code=type_code,
        engagement_id=int(engagement_id),
        user_id=int(user_id),
    )
    if fetched_reports is None:
        raise AppError(
            status_code=502,
            error_code="EXTERNAL_SERVICE_ERROR",
            message="MetSights did not return Bio AI report data for this record",
        )

    ihr.reports = fetched_reports
    ihr.report_url = report_url
    await db.flush()

    refreshed_url = await regenerate_permanent_bio_ai_report_url(
        db,
        assessment_instance_id=instance_id,
        report_url=report_url,
        engagement_id=int(engagement_id),
        user_id=int(user_id),
        assessment_date_source="engagement",
    )
    ihr.report_url = refreshed_url
    await db.flush()

    return {
        "assessment_instance_id": instance_id,
        "metsights_record_id": record_id,
        "report_url": refreshed_url,
    }
