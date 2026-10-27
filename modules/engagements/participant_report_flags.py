"""Type-aware blood / Bio AI / FitPrint flags for engagement participant rosters."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.assessments.models import AssessmentInstance, AssessmentPackage
from modules.engagements.blood_bookings_repository import current_blood_booking_subquery
from modules.engagements.models import EngagementParticipant
from modules.reports.blood_parameters_schemas import (
    has_usable_provider_blood_parameters,
    is_empty_blood_parameters,
)
from modules.reports.blood_report_archival import is_persistable_blood_report_url
from modules.reports.camp_reports_repository import _coerce_reports_dict
from modules.reports.models import IndividualHealthReport
from modules.reports.service import ReportsService

_METSIGHTS_PRO_BASIC_TYPE_CODES = ("1", "2")


def default_participant_report_flags() -> dict[str, Any]:
    return {
        "has_blood_report": False,
        "has_blood_report_raw": False,
        "has_blood_values": False,
        "has_bio_ai_report": False,
        "has_bio_ai_values": False,
        "has_bio_ai_json": False,
        "has_fitprint_report": False,
        "has_fitprint_values": False,
        "blood_report_url": None,
        "bio_ai_report_url": None,
        "fitprint_report_url": None,
    }


def _apply_ihr_row(
    flags: dict[str, Any],
    *,
    report_url: str | None,
    reports: Any,
    assessment_type_code: str | None,
) -> None:
    code = (assessment_type_code or "").strip()
    if code not in _METSIGHTS_PRO_BASIC_TYPE_CODES and code != "7":
        return

    url = str(report_url or "").strip()
    report_dict = _coerce_reports_dict(reports)
    if code in _METSIGHTS_PRO_BASIC_TYPE_CODES:
        if url:
            flags["has_bio_ai_report"] = True
            if not flags.get("bio_ai_report_url"):
                flags["bio_ai_report_url"] = url
        if report_dict and ReportsService._reports_match_assessment_type(report_dict, code):
            flags["has_bio_ai_values"] = True
            flags["has_bio_ai_json"] = True
    elif code == "7":
        if url:
            flags["has_fitprint_report"] = True
            if not flags.get("fitprint_report_url"):
                flags["fitprint_report_url"] = url
        if report_dict and ReportsService._reports_match_assessment_type(report_dict, code):
            flags["has_fitprint_values"] = True


async def engagement_report_flags_by_user(
    db: AsyncSession,
    *,
    engagement_id: int,
) -> dict[int, dict[str, Any]]:
    """Per enrolled user: blood + Bio AI (types 1/2) + FitPrint (type 7) flags."""
    curr_pbb = current_blood_booking_subquery()
    by_user: dict[int, dict[str, Any]] = {}

    ihr_result = await db.execute(
        select(
            IndividualHealthReport.user_id,
            IndividualHealthReport.report_url,
            IndividualHealthReport.reports,
            AssessmentPackage.assessment_type_code,
        )
        .select_from(IndividualHealthReport)
        .outerjoin(
            AssessmentInstance,
            AssessmentInstance.assessment_instance_id == IndividualHealthReport.assessment_instance_id,
        )
        .outerjoin(
            AssessmentPackage,
            AssessmentPackage.package_id == AssessmentInstance.package_id,
        )
        .where(IndividualHealthReport.engagement_id == engagement_id)
    )
    for row in ihr_result.all():
        uid = int(row.user_id)
        flags = by_user.setdefault(uid, default_participant_report_flags())
        _apply_ihr_row(
            flags,
            report_url=row.report_url,
            reports=row.reports,
            assessment_type_code=row.assessment_type_code,
        )

    blood_result = await db.execute(
        select(
            EngagementParticipant.user_id,
            curr_pbb.c.diagnostic_report_url,
            curr_pbb.c.blood_parameters,
            curr_pbb.c.blood_report_raw,
        )
        .select_from(EngagementParticipant)
        .join(
            curr_pbb,
            curr_pbb.c.engagement_participant_id == EngagementParticipant.engagement_participant_id,
        )
        .where(EngagementParticipant.engagement_id == engagement_id)
    )
    for row in blood_result.all():
        uid = int(row.user_id)
        flags = by_user.setdefault(uid, default_participant_report_flags())
        diagnostic_url = str(row.diagnostic_report_url or "").strip()
        if diagnostic_url:
            if not flags.get("blood_report_url"):
                flags["blood_report_url"] = diagnostic_url
            if is_persistable_blood_report_url(diagnostic_url):
                flags["has_blood_report"] = True
        if has_usable_provider_blood_parameters(row.blood_parameters):
            flags["has_blood_values"] = True
        if not is_empty_blood_parameters(row.blood_report_raw):
            flags["has_blood_report_raw"] = True

    return by_user


def merge_report_flags_into_participant_row(
    row: dict[str, Any],
    flags: dict[str, Any],
) -> None:
    """Apply completeness report flags onto a participant list row."""
    row.update(
        {
            "has_blood_report": flags["has_blood_report"],
            "has_blood_report_raw": flags["has_blood_report_raw"],
            "has_blood_values": flags["has_blood_values"],
            "has_bio_ai_report": flags["has_bio_ai_report"],
            "has_bio_ai_values": flags["has_bio_ai_values"],
            "has_bio_ai_json": flags["has_bio_ai_json"],
            "has_fitprint_report": flags["has_fitprint_report"],
            "has_fitprint_values": flags["has_fitprint_values"],
            "blood_report_url": flags.get("blood_report_url"),
            "bio_ai_report_url": flags.get("bio_ai_report_url"),
            "fitprint_report_url": flags.get("fitprint_report_url"),
        }
    )
    booking_id = row.get("booking_id")
    row["has_booking_id"] = bool(booking_id and str(booking_id).strip())


async def engagement_user_scoped_report_payloads(
    db: AsyncSession,
    *,
    engagement_id: int,
    user_id: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return (bio_ai_reports, fitprint_reports) JSON dicts for one user, or None."""
    result = await db.execute(
        select(
            IndividualHealthReport.reports,
            AssessmentPackage.assessment_type_code,
        )
        .select_from(IndividualHealthReport)
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
        )
    )
    bio: dict[str, Any] | None = None
    fitprint: dict[str, Any] | None = None
    for row in result.all():
        code = (row.assessment_type_code or "").strip()
        report_dict = _coerce_reports_dict(row.reports)
        if not report_dict or not ReportsService._reports_match_assessment_type(report_dict, code):
            continue
        if code in _METSIGHTS_PRO_BASIC_TYPE_CODES:
            bio = report_dict
        elif code == "7":
            fitprint = report_dict
    return bio, fitprint
