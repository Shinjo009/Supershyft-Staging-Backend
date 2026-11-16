"""Command-center overview metrics for admin dashboard redesign."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.assessments.models import (
    AssessmentCategoryProgress,
    AssessmentInstance,
    AssessmentPackageCategory,
)
from core.exceptions import AppError
from modules.dashboard.command_period import pick_latest_engagement
from modules.diagnostics.models import DiagnosticPackage
from modules.engagements.blood_bookings_repository import current_blood_booking_subquery
from modules.engagements.dependencies import get_engagements_repository
from modules.engagements.models import Engagement, EngagementParticipant, EngagementType
from modules.experts.models import ConsultationBooking
from modules.notifications.models import Notification
from modules.notifications.service import NotificationsService
from modules.questionnaire.models import QuestionnaireCategory
from modules.reports.models import IndividualHealthReport
from modules.users.models import User

B2B_BUCKET_STATUS: dict[str, str] = {
    "ongoing": "running",
    "upcoming": "scheduled",
    "completed": "completed",
}

VALID_B2B_BUCKETS = frozenset(B2B_BUCKET_STATUS.keys())


def _person_name(first: str | None, last: str | None) -> str:
    parts = [str(first or "").strip(), str(last or "").strip()]
    return " ".join(p for p in parts if p) or "—"


def _is_consultation_type(code: str | None, display_name: str | None) -> bool:
    blob = f"{code or ''} {display_name or ''}".strip().lower()
    return "consultation" in blob


def _questionnaire_status_label(
    *,
    has_engagement: bool,
    instance_status: str | None,
    supershyft_category_ids: list[int],
    progress_by_category: dict[int, str],
    all_required_answered: bool | None,
) -> str:
    if not has_engagement:
        return "empty"
    status = (instance_status or "").strip().lower()
    if status in ("completed", "complete"):
        return "completed"
    if supershyft_category_ids:
        if all(
            (progress_by_category.get(cid) or "").lower() in ("completed", "complete")
            for cid in supershyft_category_ids
        ):
            return "completed"
    if all_required_answered is True:
        return "completed"
    return "pending"


def _lab_status(*, has_engagement: bool, diagnostic_report_url: str | None) -> str:
    if not has_engagement:
        return "empty"
    if diagnostic_report_url and str(diagnostic_report_url).strip():
        return "loaded"
    return "pending"


def _bio_ai_status(*, has_engagement: bool, report_url: str | None) -> str:
    if not has_engagement:
        return "empty"
    if report_url and str(report_url).strip():
        return "loaded"
    return "pending"


def _consult_status(
    *,
    has_engagement: bool,
    want: bool | None,
    done: bool | None,
) -> str:
    if not has_engagement:
        return "empty"
    if done is True:
        return "Attended"
    if want is True:
        return "Booked"
    return "Not Booked"


def _audience_type(*, has_engagement: bool, organization_id: int | None) -> str:
    if not has_engagement:
        return ""
    if organization_id is not None:
        return "B2B"
    return "B2C"


async def notification_health_counts(
    db: AsyncSession,
    *,
    dispatched_from: datetime | None,
    dispatched_to: datetime | None,
) -> dict[str, int]:
    base = select(Notification.status, func.count()).select_from(Notification)
    if dispatched_from is not None:
        base = base.where(Notification.dispatched_at >= dispatched_from)
    if dispatched_to is not None:
        base = base.where(Notification.dispatched_at <= dispatched_to)
    base = base.group_by(Notification.status)
    rows = (await db.execute(base)).all()
    counts = {"sent": 0, "failed": 0, "pending": 0}
    for status, count in rows:
        key = str(status or "").strip().lower()
        if key in counts:
            counts[key] = int(count or 0)
    total = counts["sent"] + counts["failed"] + counts["pending"]
    return {**counts, "total": total}


async def failed_notifications_page(
    db: AsyncSession,
    *,
    notifications_service: NotificationsService,
    dispatched_from: datetime | None,
    dispatched_to: datetime | None,
    page: int,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    items, total = await notifications_service.list_notifications(
        db,
        page=page,
        limit=limit,
        status="failed",
        dispatched_from=dispatched_from,
        dispatched_to=dispatched_to,
    )
    rows: list[dict[str, Any]] = []
    for item in items:
        recipients = item.get("recipients") or []
        names: list[str] = []
        for r in recipients:
            if not isinstance(r, dict):
                continue
            label = _person_name(r.get("first_name"), r.get("last_name"))
            if label == "—" and r.get("name"):
                label = str(r.get("name")).strip() or "—"
            names.append(label)
        engagement = item.get("engagement_name") or item.get("engagement_code") or ""
        rows.append(
            {
                "notification_id": item.get("notification_id"),
                "recipients": ", ".join(names) if names else "—",
                "engagement": engagement or "—",
                "channel": item.get("channel") or "—",
                "message": item.get("message") or "",
            }
        )
    return rows, int(total)


async def _users_matching_period(
    db: AsyncSession,
    *,
    created_from: datetime | None,
    created_to: datetime | None,
    all_time: bool,
) -> Any:
    query = select(User).order_by(User.created_at.desc().nullslast(), User.user_id.desc())
    if all_time:
        return query
    # Ranged: require created_at and within bounds
    query = query.where(User.created_at.is_not(None))
    if created_from is not None:
        query = query.where(User.created_at >= created_from)
    if created_to is not None:
        query = query.where(User.created_at <= created_to)
    return query


async def people_registered_count(
    db: AsyncSession,
    *,
    created_from: datetime | None,
    created_to: datetime | None,
    all_time: bool,
) -> int:
    base = select(func.count()).select_from(User)
    if all_time:
        return int((await db.execute(base)).scalar_one() or 0)
    base = base.where(User.created_at.is_not(None))
    if created_from is not None:
        base = base.where(User.created_at >= created_from)
    if created_to is not None:
        base = base.where(User.created_at <= created_to)
    return int((await db.execute(base)).scalar_one() or 0)


async def people_registered_page(
    db: AsyncSession,
    *,
    created_from: datetime | None,
    created_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], int]:
    day = today or datetime.now(timezone.utc).date()
    total = await people_registered_count(
        db,
        created_from=created_from,
        created_to=created_to,
        all_time=all_time,
    )
    query = await _users_matching_period(
        db,
        created_from=created_from,
        created_to=created_to,
        all_time=all_time,
    )
    offset = max(0, (page - 1) * limit)
    users = (await db.execute(query.offset(offset).limit(limit))).scalars().all()
    if not users:
        return [], total

    user_ids = [int(u.user_id) for u in users]
    rows = await _build_people_rows(
        db,
        users=users,
        user_ids=user_ids,
        today=day,
        questionnaire_service=questionnaire_service,
    )
    return rows, total


async def _build_people_rows(
    db: AsyncSession,
    *,
    users: list[User],
    user_ids: list[int],
    today: date,
    questionnaire_service: Any | None,
) -> list[dict[str, Any]]:
    # Load all enrollments for these users
    enroll_q = (
        select(
            EngagementParticipant.user_id,
            EngagementParticipant.engagement_participant_id,
            Engagement.engagement_id,
            Engagement.engagement_name,
            Engagement.organization_id,
            Engagement.start_date,
            Engagement.diagnostic_package_id,
            Engagement.diagnostic_package_id_male,
            Engagement.diagnostic_package_id_female,
            Engagement.assessment_package_id,
            Engagement.engagement_type,
            EngagementType.code.label("type_code"),
            EngagementType.display_name.label("type_display_name"),
            User.gender,
        )
        .select_from(EngagementParticipant)
        .join(Engagement, Engagement.engagement_id == EngagementParticipant.engagement_id)
        .join(User, User.user_id == EngagementParticipant.user_id)
        .outerjoin(EngagementType, EngagementType.id == Engagement.engagement_type)
        .where(EngagementParticipant.user_id.in_(user_ids))
    )
    enroll_rows = (await db.execute(enroll_q)).all()

    by_user: dict[int, list[Any]] = {uid: [] for uid in user_ids}
    for row in enroll_rows:
        by_user[int(row.user_id)].append(row)

    latest_by_user: dict[int, Any | None] = {}
    for uid in user_ids:
        pairs = [(int(r.engagement_id), r.start_date) for r in by_user[uid]]
        chosen_id = pick_latest_engagement(pairs, today=today)
        if chosen_id is None:
            latest_by_user[uid] = None
            continue
        latest_by_user[uid] = next(
            (r for r in by_user[uid] if int(r.engagement_id) == chosen_id),
            None,
        )

    ep_ids = [
        int(r.engagement_participant_id)
        for r in latest_by_user.values()
        if r is not None
    ]
    engagement_ids = [
        int(r.engagement_id) for r in latest_by_user.values() if r is not None
    ]

    curr_pbb = current_blood_booking_subquery()
    blood_by_ep: dict[int, Any] = {}
    if ep_ids:
        blood_rows = (
            await db.execute(
                select(curr_pbb).where(curr_pbb.c.engagement_participant_id.in_(ep_ids))
            )
        ).all()
        for br in blood_rows:
            blood_by_ep[int(br.engagement_participant_id)] = br

    consult_by_ep: dict[int, list[ConsultationBooking]] = {eid: [] for eid in ep_ids}
    if ep_ids:
        consults = (
            await db.execute(
                select(ConsultationBooking).where(
                    ConsultationBooking.engagement_participant_id.in_(ep_ids)
                )
            )
        ).scalars().all()
        for c in consults:
            consult_by_ep.setdefault(int(c.engagement_participant_id), []).append(c)

    ai_by_user_eng: dict[tuple[int, int], AssessmentInstance] = {}
    if engagement_ids:
        all_inst = (
            await db.execute(
                select(AssessmentInstance).where(
                    AssessmentInstance.user_id.in_(user_ids),
                    AssessmentInstance.engagement_id.in_(engagement_ids),
                )
            )
        ).scalars().all()
        grouped: dict[tuple[int, int], list[AssessmentInstance]] = {}
        for inst in all_inst:
            grouped.setdefault((int(inst.user_id), int(inst.engagement_id)), []).append(inst)
        for uid, eng_row in latest_by_user.items():
            if eng_row is None:
                continue
            key = (uid, int(eng_row.engagement_id))
            group = grouped.get(key) or []
            if not group:
                continue
            pkg_id = eng_row.assessment_package_id
            if pkg_id is not None:
                matched = [i for i in group if int(i.package_id) == int(pkg_id)]
                if matched:
                    matched.sort(key=lambda i: int(i.assessment_instance_id))
                    ai_by_user_eng[key] = matched[0]
                    continue
            group.sort(key=lambda i: int(i.assessment_instance_id))
            ai_by_user_eng[key] = group[0]

    instance_ids = [int(i.assessment_instance_id) for i in ai_by_user_eng.values()]

    # Supershyft categories per package
    package_ids = list(
        {
            int(r.assessment_package_id)
            for r in latest_by_user.values()
            if r is not None and r.assessment_package_id is not None
        }
    )
    supershyft_cats_by_package: dict[int, list[int]] = {}
    if package_ids:
        # category_of is PG enum (NOT NULL); avoid COALESCE(enum, varchar).
        cat_rows = (
            await db.execute(
                select(
                    AssessmentPackageCategory.package_id,
                    QuestionnaireCategory.category_id,
                )
                .join(
                    QuestionnaireCategory,
                    QuestionnaireCategory.category_id == AssessmentPackageCategory.category_id,
                )
                .where(AssessmentPackageCategory.package_id.in_(package_ids))
                .where(QuestionnaireCategory.category_of == "supershyft")
            )
        ).all()
        for prow in cat_rows:
            supershyft_cats_by_package.setdefault(int(prow.package_id), []).append(
                int(prow.category_id)
            )

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

    bio_by_instance: dict[int, str | None] = {}
    if instance_ids:
        ihr_rows = (
            await db.execute(
                select(IndividualHealthReport).where(
                    IndividualHealthReport.assessment_instance_id.in_(instance_ids)
                )
            )
        ).scalars().all()
        for ihr in ihr_rows:
            if ihr.assessment_instance_id is None:
                continue
            bio_by_instance[int(ihr.assessment_instance_id)] = ihr.report_url

    # Diagnostic package names
    dx_ids: set[int] = set()
    for r in latest_by_user.values():
        if r is None:
            continue
        for attr in (
            "diagnostic_package_id",
            "diagnostic_package_id_male",
            "diagnostic_package_id_female",
        ):
            val = getattr(r, attr, None)
            if val is not None:
                dx_ids.add(int(val))
    dx_name_by_id: dict[int, str] = {}
    if dx_ids:
        pkgs = (
            await db.execute(
                select(DiagnosticPackage).where(
                    DiagnosticPackage.diagnostic_package_id.in_(list(dx_ids))
                )
            )
        ).scalars().all()
        for pkg in pkgs:
            dx_name_by_id[int(pkg.diagnostic_package_id)] = str(pkg.package_name or "")

    out: list[dict[str, Any]] = []
    for user in users:
        uid = int(user.user_id)
        eng = latest_by_user.get(uid)
        has_eng = eng is not None
        is_consult = bool(
            has_eng
            and _is_consultation_type(getattr(eng, "type_code", None), getattr(eng, "type_display_name", None))
        )

        package_name = ""
        collection = ""
        blood = "empty"
        questionnaire = "empty"
        lab = "empty"
        bio_ai = "empty"
        consult = "empty"
        engagement_name = ""
        audience = ""

        if has_eng and eng is not None:
            engagement_name = str(eng.engagement_name or "")
            audience = _audience_type(
                has_engagement=True, organization_id=eng.organization_id
            )

            if not is_consult:
                gender = str(getattr(eng, "gender", None) or getattr(user, "gender", None) or "").lower()
                dx_id = eng.diagnostic_package_id
                if dx_id is None:
                    if gender == "female" and eng.diagnostic_package_id_female is not None:
                        dx_id = eng.diagnostic_package_id_female
                    elif gender == "male" and eng.diagnostic_package_id_male is not None:
                        dx_id = eng.diagnostic_package_id_male
                    elif eng.diagnostic_package_id_male is not None:
                        dx_id = eng.diagnostic_package_id_male
                if dx_id is not None:
                    package_name = dx_name_by_id.get(int(dx_id), "") or ""

            ep_id = int(eng.engagement_participant_id)
            blood_row = blood_by_ep.get(ep_id)
            if not is_consult:
                if blood_row is not None:
                    cdate = getattr(blood_row, "collection_date", None)
                    ctime = getattr(blood_row, "collection_time", None)
                    if cdate is not None:
                        collection = str(cdate)
                        if ctime is not None:
                            collection = f"{collection} {ctime}".strip()
                    collected_at = getattr(blood_row, "collected_at", None)
                    blood = "done" if collected_at is not None else "pending"
                    report_url = getattr(blood_row, "diagnostic_report_url", None)
                    lab = _lab_status(has_engagement=True, diagnostic_report_url=report_url)
                else:
                    blood = "pending"
                    lab = "pending"
            else:
                blood = ""
                lab = ""
                # consultation: package/collection empty already

            # questionnaire + bio
            ai = ai_by_user_eng.get((uid, int(eng.engagement_id)))
            if ai is None:
                questionnaire = "pending"
                bio_ai = "pending"
            else:
                pkg_id = int(ai.package_id)
                cat_ids = supershyft_cats_by_package.get(pkg_id, [])
                progress_map = progress_by_instance.get(int(ai.assessment_instance_id), {})
                all_required: bool | None = None
                status_label = _questionnaire_status_label(
                    has_engagement=True,
                    instance_status=str(ai.status or ""),
                    supershyft_category_ids=cat_ids,
                    progress_by_category=progress_map,
                    all_required_answered=None,
                )
                if status_label == "pending" and questionnaire_service is not None and cat_ids:
                    try:
                        ok_all = True
                        for cid in cat_ids:
                            if (progress_map.get(cid) or "").lower() in ("completed", "complete"):
                                continue
                            complete = await questionnaire_service.is_category_complete(
                                db,
                                assessment_instance_id=int(ai.assessment_instance_id),
                                category_id=cid,
                                user_id=uid,
                            )
                            if not complete:
                                ok_all = False
                                break
                        all_required = ok_all
                    except Exception:
                        all_required = None
                    status_label = _questionnaire_status_label(
                        has_engagement=True,
                        instance_status=str(ai.status or ""),
                        supershyft_category_ids=cat_ids,
                        progress_by_category=progress_map,
                        all_required_answered=all_required,
                    )
                questionnaire = status_label
                bio_ai = _bio_ai_status(
                    has_engagement=True,
                    report_url=bio_by_instance.get(int(ai.assessment_instance_id)),
                )

            # consult aggregate across expert types: Attended > Booked > Not Booked
            bookings = consult_by_ep.get(ep_id) or []
            if not bookings:
                consult = "Not Booked"
            else:
                if any(bool(b.done) for b in bookings):
                    consult = "Attended"
                elif any(bool(b.want) for b in bookings):
                    consult = "Booked"
                else:
                    consult = "Not Booked"

            if is_consult:
                package_name = ""
                collection = ""
                blood = ""
                lab = ""

        out.append(
            {
                "user_id": uid,
                "person": {
                    "name": _person_name(user.first_name, user.last_name),
                    "phone": user.phone or "",
                },
                "type": audience,
                "engagement": engagement_name,
                "package": package_name,
                "collection": collection,
                "blood_collection": blood,
                "questionnaire": questionnaire,
                "lab_report": lab,
                "bio_ai": bio_ai,
                "consult": consult,
            }
        )
    return out


def _b2b_start_date_filter(
    *,
    start_from: datetime | None,
    start_to: datetime | None,
    all_time: bool,
):
    """Apply period filter on Engagement.start_date.

    Non-all_time: require non-null start_date within inclusive date bounds.
    all_time: no date filter (null start_date included).
    """
    if all_time:
        return None
    clauses = [Engagement.start_date.is_not(None)]
    if start_from is not None:
        clauses.append(Engagement.start_date >= start_from.date())
    if start_to is not None:
        clauses.append(Engagement.start_date <= start_to.date())
    return clauses


def _b2b_base_query(
    *,
    status: str,
    start_from: datetime | None,
    start_to: datetime | None,
    all_time: bool,
):
    query = select(Engagement).where(
        Engagement.organization_id.is_not(None),
        Engagement.status == status,
    )
    date_clauses = _b2b_start_date_filter(
        start_from=start_from, start_to=start_to, all_time=all_time
    )
    if date_clauses:
        query = query.where(*date_clauses)
    return query


async def b2b_summary_counts(
    db: AsyncSession,
    *,
    start_from: datetime | None,
    start_to: datetime | None,
    all_time: bool,
) -> dict[str, int]:
    out: dict[str, int] = {}
    for bucket, status in B2B_BUCKET_STATUS.items():
        query = select(func.count()).select_from(Engagement).where(
            Engagement.organization_id.is_not(None),
            Engagement.status == status,
        )
        date_clauses = _b2b_start_date_filter(
            start_from=start_from, start_to=start_to, all_time=all_time
        )
        if date_clauses:
            query = query.where(*date_clauses)
        out[bucket] = int((await db.execute(query)).scalar_one() or 0)
    return out


async def b2b_engagements_page(
    db: AsyncSession,
    *,
    bucket: str,
    start_from: datetime | None,
    start_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    key = (bucket or "").strip().lower()
    if key not in VALID_B2B_BUCKETS:
        raise AppError(
            status_code=400,
            error_code="INVALID_INPUT",
            message=f"Invalid bucket: {bucket}. Expected one of: ongoing, upcoming, completed",
        )
    status = B2B_BUCKET_STATUS[key]
    base = _b2b_base_query(
        status=status,
        start_from=start_from,
        start_to=start_to,
        all_time=all_time,
    )
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()
        or 0
    )
    offset = max(0, (page - 1) * limit)
    rows = (
        await db.execute(
            base.order_by(
                Engagement.start_date.asc().nullslast(),
                Engagement.engagement_id.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    engagement_ids = [int(e.engagement_id) for e in rows]
    repo = get_engagements_repository()
    counts = await repo.count_distinct_participants_by_engagement_ids(
        db, engagement_ids=engagement_ids
    )

    result: list[dict[str, Any]] = []
    for e in rows:
        eid = int(e.engagement_id)
        start = e.start_date
        end = e.end_date
        result.append(
            {
                "engagement_id": eid,
                "engagement_code": str(e.engagement_code or ""),
                "engagement_name": str(e.engagement_name or ""),
                "city": str(e.city or ""),
                "start_date": start.isoformat() if start else None,
                "end_date": end.isoformat() if end else None,
                "status": str(e.status or ""),
                "participant_count": int(counts.get(eid, 0)),
            }
        )
    return result, total
