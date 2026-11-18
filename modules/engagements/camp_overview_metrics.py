"""Camp progress report and day-wise summary metrics for engagement overview."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Date, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.assessments.models import (
    AssessmentCategoryProgress,
    AssessmentInstance,
    AssessmentPackageCategory,
)
from modules.engagements.blood_booking_enums import BloodBookingStatus
from modules.engagements.blood_bookings_repository import (
    countable_blood_booking_subquery,
    current_blood_booking_subquery,
)
from modules.engagements.models import Engagement, EngagementParticipant
from modules.engagements.slot_detail_dates import (
    enabled_blood_collection_dates,
    enabled_consultation_dates,
)
from modules.experts.models import ConsultationBooking
from modules.questionnaire.models import QuestionnaireCategory

_IST = ZoneInfo("Asia/Kolkata")


def _pick_primary_instance(
    instances: list[AssessmentInstance],
    assessment_package_id: int | None,
) -> AssessmentInstance | None:
    if not instances:
        return None
    if assessment_package_id is not None:
        matched = [i for i in instances if int(i.package_id) == int(assessment_package_id)]
        if matched:
            matched.sort(key=lambda i: int(i.assessment_instance_id))
            return matched[0]
    instances = sorted(instances, key=lambda i: int(i.assessment_instance_id))
    return instances[0]


def _questionnaire_is_complete(
    *,
    instance_status: str | None,
    supershyft_category_ids: list[int],
    progress_by_category: dict[int, str],
    all_required_answered: bool | None,
) -> bool:
    status = (instance_status or "").strip().lower()
    if status in ("completed", "complete"):
        return True
    if supershyft_category_ids:
        if all(
            (progress_by_category.get(cid) or "").lower() in ("completed", "complete")
            for cid in supershyft_category_ids
        ):
            return True
    if all_required_answered is True:
        return True
    return False


def _ist_date(value: datetime | None) -> date | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=_IST).astimezone(_IST).date()
    return value.astimezone(_IST).date()


async def _load_questionnaire_completion_by_user(
    db: AsyncSession,
    *,
    engagement: Engagement,
    questionnaire_service: Any | None,
) -> dict[int, dict[str, Any]]:
    """Map user_id -> {complete: bool, completed_at: datetime|None} for this engagement."""
    engagement_id = int(engagement.engagement_id)
    package_id = (
        int(engagement.assessment_package_id)
        if engagement.assessment_package_id is not None
        else None
    )

    enroll_rows = (
        await db.execute(
            select(EngagementParticipant.user_id).where(
                EngagementParticipant.engagement_id == engagement_id
            )
        )
    ).all()
    user_ids = list({int(r.user_id) for r in enroll_rows})
    if not user_ids:
        return {}

    instances = (
        await db.execute(
            select(AssessmentInstance).where(
                AssessmentInstance.engagement_id == engagement_id,
                AssessmentInstance.user_id.in_(user_ids),
            )
        )
    ).scalars().all()

    grouped: dict[int, list[AssessmentInstance]] = {}
    for inst in instances:
        grouped.setdefault(int(inst.user_id), []).append(inst)

    supershyft_cats: list[int] = []
    if package_id is not None:
        cat_rows = (
            await db.execute(
                select(QuestionnaireCategory.category_id)
                .join(
                    AssessmentPackageCategory,
                    AssessmentPackageCategory.category_id
                    == QuestionnaireCategory.category_id,
                )
                .where(AssessmentPackageCategory.package_id == package_id)
                .where(QuestionnaireCategory.category_of == "supershyft")
            )
        ).all()
        supershyft_cats = [int(r.category_id) for r in cat_rows]

    primary_by_user: dict[int, AssessmentInstance] = {}
    for uid in user_ids:
        primary = _pick_primary_instance(grouped.get(uid, []), package_id)
        if primary is not None:
            primary_by_user[uid] = primary

    instance_ids = [int(i.assessment_instance_id) for i in primary_by_user.values()]
    progress_by_instance: dict[int, dict[int, str]] = {}
    if instance_ids:
        progress_rows = (
            await db.execute(
                select(AssessmentCategoryProgress).where(
                    AssessmentCategoryProgress.assessment_instance_id.in_(instance_ids)
                )
            )
        ).scalars().all()
        for p in progress_rows:
            progress_by_instance.setdefault(int(p.assessment_instance_id), {})[
                int(p.category_id)
            ] = str(p.status or "")

    result: dict[int, dict[str, Any]] = {}
    needs_deep: list[tuple[int, AssessmentInstance, list[int], dict[int, str]]] = []

    for uid, primary in primary_by_user.items():
        iid = int(primary.assessment_instance_id)
        progress_map = progress_by_instance.get(iid, {})
        complete = _questionnaire_is_complete(
            instance_status=str(primary.status or ""),
            supershyft_category_ids=supershyft_cats,
            progress_by_category=progress_map,
            all_required_answered=None,
        )
        if complete:
            result[uid] = {
                "complete": True,
                "completed_at": primary.completed_at,
            }
        else:
            needs_deep.append((uid, primary, supershyft_cats, progress_map))

    if needs_deep and questionnaire_service is not None:
        for uid, primary, cat_ids, progress_map in needs_deep:
            if not cat_ids:
                result[uid] = {
                    "complete": False,
                    "completed_at": primary.completed_at,
                }
                continue
            try:
                ok_all = True
                for cid in cat_ids:
                    if (progress_map.get(cid) or "").lower() in ("completed", "complete"):
                        continue
                    complete = await questionnaire_service.is_category_complete(
                        db,
                        assessment_instance_id=int(primary.assessment_instance_id),
                        category_id=cid,
                        user_id=uid,
                    )
                    if not complete:
                        ok_all = False
                        break
            except Exception:
                ok_all = False
            result[uid] = {
                "complete": ok_all,
                "completed_at": primary.completed_at,
            }
    else:
        for uid, primary, _cat_ids, _progress_map in needs_deep:
            result.setdefault(
                uid,
                {"complete": False, "completed_at": primary.completed_at},
            )

    return result


async def build_progress_report(
    db: AsyncSession,
    *,
    engagement: Engagement,
    questionnaire_service: Any | None = None,
) -> dict[str, int]:
    engagement_id = int(engagement.engagement_id)

    total_registered = int(
        (
            await db.execute(
                select(func.count())
                .select_from(EngagementParticipant)
                .where(EngagementParticipant.engagement_id == engagement_id)
            )
        ).scalar_one()
        or 0
    )

    curr = current_blood_booking_subquery()
    has_booking_id = and_(
        curr.c.booking_id.is_not(None),
        func.btrim(curr.c.booking_id) != "",
    )
    blood_collected = int(
        (
            await db.execute(
                select(func.count())
                .select_from(curr)
                .join(
                    EngagementParticipant,
                    EngagementParticipant.engagement_participant_id
                    == curr.c.engagement_participant_id,
                )
                .where(EngagementParticipant.engagement_id == engagement_id)
                .where(curr.c.collected_at.is_not(None))
                .where(has_booking_id)
            )
        ).scalar_one()
        or 0
    )

    q_by_user = await _load_questionnaire_completion_by_user(
        db,
        engagement=engagement,
        questionnaire_service=questionnaire_service,
    )
    questionnaire_filled = sum(1 for row in q_by_user.values() if row.get("complete"))

    consultation_done = int(
        (
            await db.execute(
                select(func.count(func.distinct(EngagementParticipant.engagement_participant_id)))
                .select_from(ConsultationBooking)
                .join(
                    EngagementParticipant,
                    EngagementParticipant.engagement_participant_id
                    == ConsultationBooking.engagement_participant_id,
                )
                .where(EngagementParticipant.engagement_id == engagement_id)
                .where(ConsultationBooking.done.is_(True))
            )
        ).scalar_one()
        or 0
    )

    return {
        "total_registered": total_registered,
        "blood_collected": blood_collected,
        "questionnaire_filled": questionnaire_filled,
        # Placeholders until counting rules are defined.
        "blood_report_sent": 0,
        "bio_ai_report_sent": 0,
        "consultation_done": consultation_done,
    }


async def _blood_day_metrics(
    db: AsyncSession,
    *,
    engagement_id: int,
    day: date,
    q_by_user: dict[int, dict[str, Any]],
) -> dict[str, int]:
    curr = countable_blood_booking_subquery()
    is_active = curr.c.status == BloodBookingStatus.active.value
    collection_date = curr.c.collection_date
    collected_at_ist = cast(func.timezone("Asia/Kolkata", curr.c.collected_at), Date)
    has_booking_id = and_(
        curr.c.booking_id.is_not(None),
        func.btrim(curr.c.booking_id) != "",
    )

    expected = int(
        (
            await db.execute(
                select(func.count())
                .select_from(curr)
                .join(
                    EngagementParticipant,
                    EngagementParticipant.engagement_participant_id
                    == curr.c.engagement_participant_id,
                )
                .where(EngagementParticipant.engagement_id == engagement_id)
                .where(is_active)
                .where(collection_date == day)
            )
        ).scalar_one()
        or 0
    )

    sample_collected = int(
        (
            await db.execute(
                select(func.count())
                .select_from(curr)
                .join(
                    EngagementParticipant,
                    EngagementParticipant.engagement_participant_id
                    == curr.c.engagement_participant_id,
                )
                .where(EngagementParticipant.engagement_id == engagement_id)
                .where(has_booking_id)
                .where(collected_at_ist == day)
            )
        ).scalar_one()
        or 0
    )

    questionnaire_completed = sum(
        1
        for row in q_by_user.values()
        if row.get("complete") and _ist_date(row.get("completed_at")) == day
    )

    return {
        "expected_collection": expected,
        "sample_collected": sample_collected,
        "questionnaire_completed": questionnaire_completed,
    }


async def _consultation_day_metrics(
    db: AsyncSession,
    *,
    engagement_id: int,
    day: date,
) -> dict[str, int]:
    done_at_ist = cast(
        func.timezone("Asia/Kolkata", ConsultationBooking.consultation_done_at),
        Date,
    )

    want = int(
        (
            await db.execute(
                select(func.count(func.distinct(EngagementParticipant.engagement_participant_id)))
                .select_from(ConsultationBooking)
                .join(
                    EngagementParticipant,
                    EngagementParticipant.engagement_participant_id
                    == ConsultationBooking.engagement_participant_id,
                )
                .where(EngagementParticipant.engagement_id == engagement_id)
                .where(ConsultationBooking.want.is_(True))
                .where(ConsultationBooking.consultation_date == day)
            )
        ).scalar_one()
        or 0
    )

    done = int(
        (
            await db.execute(
                select(func.count(func.distinct(EngagementParticipant.engagement_participant_id)))
                .select_from(ConsultationBooking)
                .join(
                    EngagementParticipant,
                    EngagementParticipant.engagement_participant_id
                    == ConsultationBooking.engagement_participant_id,
                )
                .where(EngagementParticipant.engagement_id == engagement_id)
                .where(ConsultationBooking.done.is_(True))
                .where(done_at_ist == day)
            )
        ).scalar_one()
        or 0
    )

    return {
        "consultation_want": want,
        "consultation_done": done,
    }


async def build_day_wise_summary(
    db: AsyncSession,
    *,
    engagement: Engagement,
    slot_detail: dict[str, Any] | None,
    section: str | None = None,
    date_filter: date | None = None,
    questionnaire_service: Any | None = None,
) -> dict[str, Any]:
    engagement_id = int(engagement.engagement_id)
    blood_dates = enabled_blood_collection_dates(slot_detail)
    consultation_dates = enabled_consultation_dates(slot_detail)

    include_blood = section in (None, "blood_collection", "both", "")
    include_consultation = section in (None, "consultation", "both", "")

    blood_by_date: dict[str, dict[str, int]] = {}
    consultation_by_date: dict[str, dict[str, int]] = {}

    q_by_user: dict[int, dict[str, Any]] = {}
    if include_blood:
        q_by_user = await _load_questionnaire_completion_by_user(
            db,
            engagement=engagement,
            questionnaire_service=questionnaire_service,
        )
        days = [date_filter] if date_filter is not None else blood_dates
        for day in days:
            if day is None:
                continue
            blood_by_date[day.isoformat()] = await _blood_day_metrics(
                db,
                engagement_id=engagement_id,
                day=day,
                q_by_user=q_by_user,
            )

    if include_consultation:
        days = [date_filter] if date_filter is not None else consultation_dates
        for day in days:
            if day is None:
                continue
            consultation_by_date[day.isoformat()] = await _consultation_day_metrics(
                db,
                engagement_id=engagement_id,
                day=day,
            )

    return {
        "blood_collection_dates": [d.isoformat() for d in blood_dates],
        "consultation_dates": [d.isoformat() for d in consultation_dates],
        "blood_collection": blood_by_date,
        "consultation": consultation_by_date,
    }
