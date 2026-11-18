"""Shared camp KPI questionnaire completion rules (MetSights Pro/Basic)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.assessments.models import (
    AssessmentCategoryProgress,
    AssessmentInstance,
    AssessmentPackage,
    AssessmentPackageCategory,
)
from modules.engagements.models import EngagementParticipant
from modules.questionnaire.models import (
    QuestionnaireCategory,
    QuestionnaireCategoryQuestion,
    QuestionnaireDefinition,
    QuestionnaireResponse,
)

_IST = ZoneInfo("Asia/Kolkata")

METSIGHTS_PRO_BASIC_TYPE_CODES = ("1", "2")
METSIGHTS_CATEGORY_KEYS = (
    "physical-measurement",
    "diet-lifestyle-parameters",
    "vitals",
    "fitness-parameters",
)
# KPI questionnaire_completed requires these Metsights categories when assigned.
# Vitals is camp-day data and is intentionally excluded from this set.
KPI_QUESTIONNAIRE_REQUIRED_CATEGORY_KEYS = (
    "physical-measurement",
    "diet-lifestyle-parameters",
    "fitness-parameters",
)

_INSTANCE_ROW = tuple[int, int, int, int]  # iid, uid, package_id, engagement_id


@dataclass
class KpiQuestionnaireData:
    instance_rows: list[_INSTANCE_ROW] = field(default_factory=list)
    instances_by_eng: dict[int, list[_INSTANCE_ROW]] = field(default_factory=dict)
    progress_map: dict[int, dict[str, dict[str, Any]]] = field(default_factory=dict)
    resp_counts: dict[int, int] = field(default_factory=dict)
    pkg_categories: dict[int, set[str]] = field(default_factory=dict)
    cat_resp_map: dict[int, dict[str, bool]] = field(default_factory=dict)
    unanswered_map: dict[int, dict[str, list[dict]]] = field(default_factory=dict)


def _ist_date(value: datetime | None) -> date | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=_IST).astimezone(_IST).date()
    return value.astimezone(_IST).date()


def _category_effective_status(
    *,
    cat_status: str,
    has_resp: bool,
    unanswered: list[dict],
) -> str:
    if cat_status != "complete" and has_resp and not unanswered:
        return "complete"
    return cat_status


def rollup_questionnaire_kpi_for_engagement(
    *,
    scoped_users: set[int],
    instance_rows: list[_INSTANCE_ROW],
    data: KpiQuestionnaireData,
) -> dict[str, Any]:
    """Return filled / partial / not_started counts and per-user detail for one engagement."""
    user_data: dict[int, dict[str, Any]] = {}

    for row in instance_rows:
        iid = int(row[0])
        uid = int(row[1])
        pid = int(row[2])
        if uid not in scoped_users:
            continue
        assigned_cats = data.pkg_categories.get(pid, set())
        entry = user_data.setdefault(
            uid,
            {
                "assigned_cats": set(),
                "has_any_responses": False,
                "all_assigned_complete": True,
                "unanswered_questions": [],
                "completion_at": None,
            },
        )
        entry["assigned_cats"].update(assigned_cats)
        if data.resp_counts.get(iid, 0) > 0:
            entry["has_any_responses"] = True
        inst_progress = data.progress_map.get(iid, {})
        for ck in KPI_QUESTIONNAIRE_REQUIRED_CATEGORY_KEYS:
            if ck not in assigned_cats:
                continue
            prog = inst_progress.get(ck, {})
            has_resp = data.cat_resp_map.get(iid, {}).get(ck, False)
            cat_status = prog.get("status", "incomplete")
            unanswered = data.unanswered_map.get(iid, {}).get(ck, [])
            cat_status = _category_effective_status(
                cat_status=cat_status,
                has_resp=has_resp,
                unanswered=unanswered,
            )
            if cat_status != "complete":
                entry["all_assigned_complete"] = False
                for q in unanswered:
                    text = str(q.get("question_text") or "").strip()
                    if text and text not in entry["unanswered_questions"]:
                        entry["unanswered_questions"].append(text)
            elif prog.get("completed_at") is not None:
                completed_at = prog["completed_at"]
                prev = entry.get("completion_at")
                if prev is None or completed_at > prev:
                    entry["completion_at"] = completed_at

    for uid in scoped_users:
        if uid not in user_data:
            user_data[uid] = {
                "assigned_cats": set(),
                "has_any_responses": False,
                "all_assigned_complete": True,
                "unanswered_questions": [],
                "completion_at": None,
            }

    filled = partial = not_started = 0
    filled_user_ids: set[int] = set()
    filled_completion_at: dict[int, datetime | None] = {}
    user_states: dict[int, str] = {}
    unanswered_by_user: dict[int, list[str]] = {}

    for uid, entry in user_data.items():
        assigned = entry["assigned_cats"]
        if not assigned:
            state = "not_started"
            not_started += 1
        elif entry["all_assigned_complete"]:
            state = "filled"
            filled += 1
            filled_user_ids.add(uid)
            filled_completion_at[uid] = entry.get("completion_at")
        elif entry["has_any_responses"]:
            state = "partially_filled"
            partial += 1
        else:
            state = "not_started"
            not_started += 1

        user_states[uid] = state
        if entry.get("unanswered_questions"):
            unanswered_by_user[uid] = list(entry["unanswered_questions"])

    return {
        "filled": filled,
        "partially_filled": partial,
        "not_started": not_started,
        "enrolled": len(scoped_users),
        "filled_user_ids": filled_user_ids,
        "filled_completion_at_by_user": filled_completion_at,
        "user_states": user_states,
        "unanswered_by_user": unanswered_by_user,
    }


async def load_kpi_questionnaire_data(
    db: AsyncSession,
    *,
    engagement_ids: list[int],
    user_ids: set[int] | None = None,
) -> KpiQuestionnaireData | None:
    """Load instances, progress, responses, and unanswered required questions for KPI rules."""
    if not engagement_ids:
        return None

    instances_query = (
        select(
            AssessmentInstance.assessment_instance_id,
            AssessmentInstance.user_id,
            AssessmentInstance.package_id,
            AssessmentInstance.engagement_id,
        )
        .join(
            AssessmentPackage,
            AssessmentPackage.package_id == AssessmentInstance.package_id,
        )
        .where(AssessmentInstance.engagement_id.in_(engagement_ids))
        .where(AssessmentPackage.assessment_type_code.in_(METSIGHTS_PRO_BASIC_TYPE_CODES))
    )
    if user_ids is not None:
        if not user_ids:
            return KpiQuestionnaireData()
        instances_query = instances_query.where(AssessmentInstance.user_id.in_(user_ids))

    instance_rows_raw = (await db.execute(instances_query)).all()
    instance_rows: list[_INSTANCE_ROW] = [
        (int(r[0]), int(r[1]), int(r[2]), int(r[3])) for r in instance_rows_raw
    ]
    if not instance_rows:
        return KpiQuestionnaireData()

    instance_ids = [int(r[0]) for r in instance_rows]
    package_ids = list({int(r[2]) for r in instance_rows})

    progress_query = (
        select(
            AssessmentCategoryProgress.assessment_instance_id,
            AssessmentCategoryProgress.category_id,
            AssessmentCategoryProgress.status,
            AssessmentCategoryProgress.is_submitted,
            AssessmentCategoryProgress.completed_at,
            QuestionnaireCategory.category_key,
        )
        .join(
            QuestionnaireCategory,
            QuestionnaireCategory.category_id == AssessmentCategoryProgress.category_id,
        )
        .where(AssessmentCategoryProgress.assessment_instance_id.in_(instance_ids))
    )
    progress_map: dict[int, dict[str, dict[str, Any]]] = {}
    for p in (await db.execute(progress_query)).all():
        ck = p.category_key
        if ck is None:
            continue
        progress_map.setdefault(int(p.assessment_instance_id), {})[ck] = {
            "status": p.status,
            "is_submitted": bool(p.is_submitted),
            "completed_at": p.completed_at,
        }

    resp_count_query = (
        select(
            QuestionnaireResponse.assessment_instance_id,
            func.count(QuestionnaireResponse.response_id),
        )
        .where(QuestionnaireResponse.assessment_instance_id.in_(instance_ids))
        .group_by(QuestionnaireResponse.assessment_instance_id)
    )
    resp_counts = {
        int(r[0]): int(r[1]) for r in (await db.execute(resp_count_query)).all()
    }

    pkg_cat_query = (
        select(
            AssessmentPackageCategory.package_id,
            QuestionnaireCategory.category_key,
        )
        .join(
            QuestionnaireCategory,
            QuestionnaireCategory.category_id == AssessmentPackageCategory.category_id,
        )
        .where(AssessmentPackageCategory.package_id.in_(package_ids))
        .where(QuestionnaireCategory.category_of == "metsights")
    )
    pkg_categories: dict[int, set[str]] = {}
    for pc in (await db.execute(pkg_cat_query)).all():
        pkg_categories.setdefault(int(pc.package_id), set()).add(pc.category_key)

    cat_key_to_id: dict[str, int] = {}
    for ck in METSIGHTS_CATEGORY_KEYS:
        cat_row = await db.execute(
            select(QuestionnaireCategory.category_id)
            .where(QuestionnaireCategory.category_key == ck)
            .where(QuestionnaireCategory.category_of == "metsights")
            .limit(1)
        )
        cid = cat_row.scalar_one_or_none()
        if cid is not None:
            cat_key_to_id[ck] = int(cid)

    cat_resp_map: dict[int, dict[str, bool]] = {iid: {} for iid in instance_ids}
    for ck, cid in cat_key_to_id.items():
        has_resp_query = (
            select(
                QuestionnaireResponse.assessment_instance_id,
                func.count(QuestionnaireResponse.response_id),
            )
            .where(QuestionnaireResponse.assessment_instance_id.in_(instance_ids))
            .where(QuestionnaireResponse.category_ids.any(cid))
            .group_by(QuestionnaireResponse.assessment_instance_id)
        )
        for r in (await db.execute(has_resp_query)).all():
            cat_resp_map.setdefault(int(r[0]), {})[ck] = int(r[1]) > 0

    unanswered_map: dict[int, dict[str, list[dict]]] = {}
    for ck, cid in cat_key_to_id.items():
        unanswered_query = (
            select(
                AssessmentInstance.assessment_instance_id,
                QuestionnaireDefinition.question_id,
                QuestionnaireDefinition.question_text,
            )
            .select_from(AssessmentInstance)
            .join(
                AssessmentPackageCategory,
                AssessmentPackageCategory.package_id == AssessmentInstance.package_id,
            )
            .join(
                QuestionnaireCategoryQuestion,
                QuestionnaireCategoryQuestion.category_id
                == AssessmentPackageCategory.category_id,
            )
            .join(
                QuestionnaireDefinition,
                QuestionnaireDefinition.question_id
                == QuestionnaireCategoryQuestion.question_id,
            )
            .outerjoin(
                QuestionnaireResponse,
                (QuestionnaireResponse.assessment_instance_id
                 == AssessmentInstance.assessment_instance_id)
                & (QuestionnaireResponse.question_id == QuestionnaireDefinition.question_id)
                & (QuestionnaireResponse.category_ids.any(cid)),
            )
            .where(AssessmentInstance.assessment_instance_id.in_(instance_ids))
            .where(AssessmentPackageCategory.category_id == cid)
            .where(QuestionnaireDefinition.is_required.is_(True))
            .where(QuestionnaireResponse.response_id.is_(None))
            .order_by(
                AssessmentInstance.assessment_instance_id.asc(),
                QuestionnaireDefinition.question_id.asc(),
            )
        )
        for r in (await db.execute(unanswered_query)).all():
            unanswered_map.setdefault(int(r.assessment_instance_id), {}).setdefault(
                ck, []
            ).append(
                {
                    "question_id": int(r.question_id),
                    "question_text": r.question_text,
                }
            )

    instances_by_eng: dict[int, list[_INSTANCE_ROW]] = {eid: [] for eid in engagement_ids}
    for row in instance_rows:
        instances_by_eng.setdefault(int(row[3]), []).append(row)

    return KpiQuestionnaireData(
        instance_rows=instance_rows,
        instances_by_eng=instances_by_eng,
        progress_map=progress_map,
        resp_counts=resp_counts,
        pkg_categories=pkg_categories,
        cat_resp_map=cat_resp_map,
        unanswered_map=unanswered_map,
    )


async def questionnaire_kpi_counts_for_engagement(
    db: AsyncSession,
    *,
    engagement_id: int,
) -> dict[str, Any]:
    """Questionnaire filled / partial / not_started for one engagement (camp KPI rules)."""
    enrolled_rows = (
        await db.execute(
            select(EngagementParticipant.user_id).where(
                EngagementParticipant.engagement_id == engagement_id
            )
        )
    ).all()
    scoped_users = {int(r.user_id) for r in enrolled_rows}
    if not scoped_users:
        return {
            "filled": 0,
            "partially_filled": 0,
            "not_started": 0,
            "enrolled": 0,
            "filled_user_ids": set(),
            "filled_completion_at_by_user": {},
        }

    data = await load_kpi_questionnaire_data(
        db,
        engagement_ids=[engagement_id],
        user_ids=scoped_users,
    )
    if data is None or not data.instance_rows:
        return {
            "filled": 0,
            "partially_filled": 0,
            "not_started": len(scoped_users),
            "enrolled": len(scoped_users),
            "filled_user_ids": set(),
            "filled_completion_at_by_user": {},
        }

    return rollup_questionnaire_kpi_for_engagement(
        scoped_users=scoped_users,
        instance_rows=data.instances_by_eng.get(engagement_id, []),
        data=data,
    )


def count_questionnaire_completed_on_day(
    *,
    filled_completion_at_by_user: dict[int, datetime | None],
    day: date,
) -> int:
    """Count KPI-filled users whose latest required-category completion falls on ``day`` (IST)."""
    count = 0
    for completed_at in filled_completion_at_by_user.values():
        if _ist_date(completed_at) == day:
            count += 1
    return count