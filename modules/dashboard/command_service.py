"""Command-center overview metrics for admin dashboard redesign."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
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
from modules.support.models import SupportTicket
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
    """Label for B2B command dashboard rows (SuperShyft package categories).

    Camp engagement overview and camp-report KPIs use
    ``modules.reports.questionnaire_kpi_completion`` (MetSights required keys).
    """
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


def _audience_split_counts(
    audience_by_user: dict[int, str],
) -> dict[str, int]:
    b2b = sum(1 for a in audience_by_user.values() if a == "B2B")
    b2c = sum(1 for a in audience_by_user.values() if a == "B2C")
    return {"total": len(audience_by_user), "b2b": b2b, "b2c": b2c}


async def _tests_completed_audience_by_user(
    db: AsyncSession,
    *,
    collected_from: datetime | None,
    collected_to: datetime | None,
    all_time: bool,
) -> dict[int, str]:
    """Distinct users with current blood booking collected; one audience per user.

    Latest collected_at wins when a user has multiple completed collections.
    Period filter uses participant_blood_bookings.collected_at; nulls excluded
    from ranged filters (and from the KPI entirely).
    """
    curr_pbb = current_blood_booking_subquery()
    query = (
        select(
            EngagementParticipant.user_id,
            Engagement.organization_id,
            curr_pbb.c.collected_at,
            EngagementParticipant.engagement_participant_id,
        )
        .select_from(curr_pbb)
        .join(
            EngagementParticipant,
            EngagementParticipant.engagement_participant_id
            == curr_pbb.c.engagement_participant_id,
        )
        .join(
            Engagement,
            Engagement.engagement_id == EngagementParticipant.engagement_id,
        )
        .where(curr_pbb.c.collected_at.is_not(None))
    )
    if not all_time:
        if collected_from is not None:
            query = query.where(curr_pbb.c.collected_at >= collected_from)
        if collected_to is not None:
            query = query.where(curr_pbb.c.collected_at <= collected_to)

    rows = (await db.execute(query)).all()
    best: dict[int, tuple[datetime, int | None, int]] = {}
    for row in rows:
        uid = int(row.user_id)
        collected_at = row.collected_at
        ep_id = int(row.engagement_participant_id)
        prev = best.get(uid)
        if prev is None or (
            collected_at is not None
            and (prev[0] is None or collected_at > prev[0] or (collected_at == prev[0] and ep_id > prev[2]))
        ):
            best[uid] = (collected_at, row.organization_id, ep_id)

    return {
        uid: _audience_type(has_engagement=True, organization_id=org_id)
        for uid, (_ca, org_id, _ep) in best.items()
    }


async def tests_completed_counts(
    db: AsyncSession,
    *,
    collected_from: datetime | None,
    collected_to: datetime | None,
    all_time: bool,
) -> dict[str, int]:
    audience = await _tests_completed_audience_by_user(
        db,
        collected_from=collected_from,
        collected_to=collected_to,
        all_time=all_time,
    )
    return _audience_split_counts(audience)


async def tests_completed_page(
    db: AsyncSession,
    *,
    collected_from: datetime | None,
    collected_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    day = today or datetime.now(timezone.utc).date()
    audience = await _tests_completed_audience_by_user(
        db,
        collected_from=collected_from,
        collected_to=collected_to,
        all_time=all_time,
    )
    counts = _audience_split_counts(audience)
    user_ids = sorted(audience.keys(), reverse=True)
    offset = max(0, (page - 1) * limit)
    page_ids = user_ids[offset : offset + limit]
    if not page_ids:
        return [], counts

    users = (
        await db.execute(
            select(User)
            .where(User.user_id.in_(page_ids))
            .order_by(User.user_id.desc())
        )
    ).scalars().all()
    # Preserve sorted order (user_id desc)
    by_id = {int(u.user_id): u for u in users}
    ordered = [by_id[uid] for uid in page_ids if uid in by_id]
    rows = await _build_people_rows(
        db,
        users=ordered,
        user_ids=[int(u.user_id) for u in ordered],
        today=day,
        questionnaire_service=questionnaire_service,
    )
    return rows, counts


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


async def _questionnaire_done_audience_by_user(
    db: AsyncSession,
    *,
    completed_from: datetime | None,
    completed_to: datetime | None,
    all_time: bool,
    questionnaire_service: Any | None = None,
) -> dict[int, str]:
    """Users whose primary assessment questionnaire is completed.

    Ranged periods: only rows with assessment_instances.completed_at in bounds
    (null completed_at ignored). All-time: also include category-complete /
    all-required-answered paths even when completed_at is null.
    """
    enroll_q = (
        select(
            EngagementParticipant.user_id,
            EngagementParticipant.engagement_participant_id,
            Engagement.engagement_id,
            Engagement.organization_id,
            Engagement.assessment_package_id,
        )
        .select_from(EngagementParticipant)
        .join(Engagement, Engagement.engagement_id == EngagementParticipant.engagement_id)
    )
    enroll_rows = (await db.execute(enroll_q)).all()
    if not enroll_rows:
        return {}

    user_ids = list({int(r.user_id) for r in enroll_rows})
    engagement_ids = list({int(r.engagement_id) for r in enroll_rows})

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

    package_ids = list(
        {
            int(r.assessment_package_id)
            for r in enroll_rows
            if r.assessment_package_id is not None
        }
    )
    supershyft_cats_by_package: dict[int, list[int]] = {}
    if package_ids:
        cat_rows = (
            await db.execute(
                select(
                    AssessmentPackageCategory.package_id,
                    QuestionnaireCategory.category_id,
                )
                .join(
                    QuestionnaireCategory,
                    QuestionnaireCategory.category_id
                    == AssessmentPackageCategory.category_id,
                )
                .where(AssessmentPackageCategory.package_id.in_(package_ids))
                .where(QuestionnaireCategory.category_of == "supershyft")
            )
        ).all()
        for prow in cat_rows:
            supershyft_cats_by_package.setdefault(int(prow.package_id), []).append(
                int(prow.category_id)
            )

    instance_ids = [int(i.assessment_instance_id) for i in all_inst]
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

    # Candidates: (user_id, completed_at, organization_id, instance, cat_ids, progress)
    candidates: list[tuple[int, datetime | None, int | None, AssessmentInstance, list[int], dict[int, str]]] = []
    for row in enroll_rows:
        uid = int(row.user_id)
        eng_id = int(row.engagement_id)
        primary = _pick_primary_instance(
            grouped.get((uid, eng_id), []),
            row.assessment_package_id,
        )
        if primary is None:
            continue
        completed_at = primary.completed_at
        if not all_time:
            if completed_at is None:
                continue
            if completed_from is not None and completed_at < completed_from:
                continue
            if completed_to is not None and completed_at > completed_to:
                continue
        pkg_id = int(primary.package_id)
        cat_ids = supershyft_cats_by_package.get(pkg_id, [])
        progress_map = progress_by_instance.get(int(primary.assessment_instance_id), {})
        candidates.append(
            (uid, completed_at, row.organization_id, primary, cat_ids, progress_map)
        )

    # Ranged: completed_at in bounds is the completion stamp.
    # All-time: full OR (instance status / supershyft cats / required answered).
    qualified: list[tuple[int, datetime | None, int | None, int]] = []
    needs_deep: list[
        tuple[int, datetime | None, int | None, AssessmentInstance, list[int], dict[int, str]]
    ] = []

    for uid, completed_at, org_id, primary, cat_ids, progress_map in candidates:
        iid = int(primary.assessment_instance_id)
        if not all_time:
            qualified.append((uid, completed_at, org_id, iid))
            continue
        label = _questionnaire_status_label(
            has_engagement=True,
            instance_status=str(primary.status or ""),
            supershyft_category_ids=cat_ids,
            progress_by_category=progress_map,
            all_required_answered=None,
        )
        if label == "completed":
            qualified.append((uid, completed_at, org_id, iid))
        else:
            needs_deep.append((uid, completed_at, org_id, primary, cat_ids, progress_map))

    if needs_deep and questionnaire_service is not None:
        for uid, completed_at, org_id, primary, cat_ids, progress_map in needs_deep:
            if not cat_ids:
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
            if ok_all:
                qualified.append(
                    (uid, completed_at, org_id, int(primary.assessment_instance_id))
                )

    # One audience per user: prefer latest completed_at, then highest instance id
    best: dict[int, tuple[datetime | None, int | None, int]] = {}
    for uid, completed_at, org_id, instance_id in qualified:
        prev = best.get(uid)
        if prev is None:
            best[uid] = (completed_at, org_id, instance_id)
            continue
        prev_ca, _prev_org, prev_iid = prev
        if completed_at is not None and (prev_ca is None or completed_at > prev_ca):
            best[uid] = (completed_at, org_id, instance_id)
        elif completed_at == prev_ca and instance_id > prev_iid:
            best[uid] = (completed_at, org_id, instance_id)

    return {
        uid: _audience_type(has_engagement=True, organization_id=org_id)
        for uid, (_ca, org_id, _iid) in best.items()
    }


async def questionnaire_done_counts(
    db: AsyncSession,
    *,
    completed_from: datetime | None,
    completed_to: datetime | None,
    all_time: bool,
    questionnaire_service: Any | None = None,
) -> dict[str, int]:
    audience = await _questionnaire_done_audience_by_user(
        db,
        completed_from=completed_from,
        completed_to=completed_to,
        all_time=all_time,
        questionnaire_service=questionnaire_service,
    )
    return _audience_split_counts(audience)


async def questionnaire_done_page(
    db: AsyncSession,
    *,
    completed_from: datetime | None,
    completed_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    day = today or datetime.now(timezone.utc).date()
    audience = await _questionnaire_done_audience_by_user(
        db,
        completed_from=completed_from,
        completed_to=completed_to,
        all_time=all_time,
        questionnaire_service=questionnaire_service,
    )
    counts = _audience_split_counts(audience)
    user_ids = sorted(audience.keys(), reverse=True)
    offset = max(0, (page - 1) * limit)
    page_ids = user_ids[offset : offset + limit]
    if not page_ids:
        return [], counts

    users = (
        await db.execute(
            select(User)
            .where(User.user_id.in_(page_ids))
            .order_by(User.user_id.desc())
        )
    ).scalars().all()
    by_id = {int(u.user_id): u for u in users}
    ordered = [by_id[uid] for uid in page_ids if uid in by_id]
    rows = await _build_people_rows(
        db,
        users=ordered,
        user_ids=[int(u.user_id) for u in ordered],
        today=day,
        questionnaire_service=questionnaire_service,
    )
    return rows, counts


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


def _stamp_period_clauses(
    column,
    *,
    stamp_from: datetime | None,
    stamp_to: datetime | None,
    all_time: bool,
):
    """Null stamps are excluded from ranged filters; included only for all_time."""
    if all_time:
        return []
    clauses = [column.is_not(None)]
    if stamp_from is not None:
        clauses.append(column >= stamp_from)
    if stamp_to is not None:
        clauses.append(column <= stamp_to)
    return clauses


def _date_period_clauses(
    column,
    *,
    stamp_from: datetime | None,
    stamp_to: datetime | None,
    all_time: bool,
):
    """Period filter for Date columns (inclusive calendar-day bounds)."""
    if all_time:
        return []
    clauses = [column.is_not(None)]
    if stamp_from is not None:
        clauses.append(column >= stamp_from.date())
    if stamp_to is not None:
        clauses.append(column <= stamp_to.date())
    return clauses


def _stamp_in_period(
    stamp: datetime | None,
    *,
    stamp_from: datetime | None,
    stamp_to: datetime | None,
    all_time: bool,
) -> bool:
    if all_time:
        return True
    if stamp is None:
        return False
    if stamp_from is not None and stamp < stamp_from:
        return False
    if stamp_to is not None and stamp > stamp_to:
        return False
    return True


async def _people_page_for_audience(
    db: AsyncSession,
    *,
    audience: dict[int, str],
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    day = today or datetime.now(timezone.utc).date()
    counts = _audience_split_counts(audience)
    user_ids = sorted(audience.keys(), reverse=True)
    offset = max(0, (page - 1) * limit)
    page_ids = user_ids[offset : offset + limit]
    if not page_ids:
        return [], counts

    users = (
        await db.execute(
            select(User)
            .where(User.user_id.in_(page_ids))
            .order_by(User.user_id.desc())
        )
    ).scalars().all()
    by_id = {int(u.user_id): u for u in users}
    ordered = [by_id[uid] for uid in page_ids if uid in by_id]
    rows = await _build_people_rows(
        db,
        users=ordered,
        user_ids=[int(u.user_id) for u in ordered],
        today=day,
        questionnaire_service=questionnaire_service,
    )
    return rows, counts


async def _blood_report_audience_by_user(
    db: AsyncSession,
    *,
    received_from: datetime | None,
    received_to: datetime | None,
    all_time: bool,
) -> dict[int, str]:
    """Distinct users whose current blood booking has a diagnostic report URL."""
    curr_pbb = current_blood_booking_subquery()
    query = (
        select(
            EngagementParticipant.user_id,
            Engagement.organization_id,
            curr_pbb.c.report_received_at,
            EngagementParticipant.engagement_participant_id,
        )
        .select_from(curr_pbb)
        .join(
            EngagementParticipant,
            EngagementParticipant.engagement_participant_id
            == curr_pbb.c.engagement_participant_id,
        )
        .join(
            Engagement,
            Engagement.engagement_id == EngagementParticipant.engagement_id,
        )
        .where(
            curr_pbb.c.diagnostic_report_url.is_not(None),
            func.btrim(curr_pbb.c.diagnostic_report_url) != "",
        )
    )
    for clause in _stamp_period_clauses(
        curr_pbb.c.report_received_at,
        stamp_from=received_from,
        stamp_to=received_to,
        all_time=all_time,
    ):
        query = query.where(clause)

    rows = (await db.execute(query)).all()
    best: dict[int, tuple[datetime | None, int | None, int]] = {}
    for row in rows:
        uid = int(row.user_id)
        received_at = row.report_received_at
        ep_id = int(row.engagement_participant_id)
        prev = best.get(uid)
        if prev is None or (
            received_at is not None
            and (
                prev[0] is None
                or received_at > prev[0]
                or (received_at == prev[0] and ep_id > prev[2])
            )
        ):
            best[uid] = (received_at, row.organization_id, ep_id)

    return {
        uid: _audience_type(has_engagement=True, organization_id=org_id)
        for uid, (_ra, org_id, _ep) in best.items()
    }


async def blood_report_generated_counts(
    db: AsyncSession,
    *,
    received_from: datetime | None,
    received_to: datetime | None,
    all_time: bool,
) -> dict[str, int]:
    audience = await _blood_report_audience_by_user(
        db,
        received_from=received_from,
        received_to=received_to,
        all_time=all_time,
    )
    return _audience_split_counts(audience)


async def blood_report_generated_page(
    db: AsyncSession,
    *,
    received_from: datetime | None,
    received_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    audience = await _blood_report_audience_by_user(
        db,
        received_from=received_from,
        received_to=received_to,
        all_time=all_time,
    )
    return await _people_page_for_audience(
        db,
        audience=audience,
        page=page,
        limit=limit,
        today=today,
        questionnaire_service=questionnaire_service,
    )


async def _bioai_report_audience_by_user(
    db: AsyncSession,
    *,
    received_from: datetime | None,
    received_to: datetime | None,
    all_time: bool,
) -> dict[int, str]:
    """Distinct users with an IHR that has a BioAI report_url."""
    query = (
        select(
            IndividualHealthReport.user_id,
            Engagement.organization_id,
            IndividualHealthReport.report_received_at,
            IndividualHealthReport.report_id,
        )
        .select_from(IndividualHealthReport)
        .join(
            Engagement,
            Engagement.engagement_id == IndividualHealthReport.engagement_id,
        )
        .where(
            IndividualHealthReport.report_url.is_not(None),
            func.btrim(IndividualHealthReport.report_url) != "",
        )
    )
    for clause in _stamp_period_clauses(
        IndividualHealthReport.report_received_at,
        stamp_from=received_from,
        stamp_to=received_to,
        all_time=all_time,
    ):
        query = query.where(clause)

    rows = (await db.execute(query)).all()
    best: dict[int, tuple[datetime | None, int | None, int]] = {}
    for row in rows:
        uid = int(row.user_id)
        received_at = row.report_received_at
        report_id = int(row.report_id)
        prev = best.get(uid)
        if prev is None or (
            received_at is not None
            and (
                prev[0] is None
                or received_at > prev[0]
                or (received_at == prev[0] and report_id > prev[2])
            )
        ):
            best[uid] = (received_at, row.organization_id, report_id)

    return {
        uid: _audience_type(has_engagement=True, organization_id=org_id)
        for uid, (_ra, org_id, _rid) in best.items()
    }


async def bioai_report_generated_counts(
    db: AsyncSession,
    *,
    received_from: datetime | None,
    received_to: datetime | None,
    all_time: bool,
) -> dict[str, int]:
    audience = await _bioai_report_audience_by_user(
        db,
        received_from=received_from,
        received_to=received_to,
        all_time=all_time,
    )
    return _audience_split_counts(audience)


async def bioai_report_generated_page(
    db: AsyncSession,
    *,
    received_from: datetime | None,
    received_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    audience = await _bioai_report_audience_by_user(
        db,
        received_from=received_from,
        received_to=received_to,
        all_time=all_time,
    )
    return await _people_page_for_audience(
        db,
        audience=audience,
        page=page,
        limit=limit,
        today=today,
        questionnaire_service=questionnaire_service,
    )


async def _consultation_done_audience_by_user(
    db: AsyncSession,
    *,
    done_from: datetime | None,
    done_to: datetime | None,
    all_time: bool,
) -> dict[int, str]:
    """Distinct users with at least one consultation booking marked done."""
    query = (
        select(
            EngagementParticipant.user_id,
            Engagement.organization_id,
            ConsultationBooking.consultation_done_at,
            ConsultationBooking.consultation_id,
        )
        .select_from(ConsultationBooking)
        .join(
            EngagementParticipant,
            EngagementParticipant.engagement_participant_id
            == ConsultationBooking.engagement_participant_id,
        )
        .join(
            Engagement,
            Engagement.engagement_id == EngagementParticipant.engagement_id,
        )
        .where(ConsultationBooking.done.is_(True))
    )
    for clause in _stamp_period_clauses(
        ConsultationBooking.consultation_done_at,
        stamp_from=done_from,
        stamp_to=done_to,
        all_time=all_time,
    ):
        query = query.where(clause)

    rows = (await db.execute(query)).all()
    best: dict[int, tuple[datetime | None, int | None, int]] = {}
    for row in rows:
        uid = int(row.user_id)
        done_at = row.consultation_done_at
        cid = int(row.consultation_id)
        prev = best.get(uid)
        if prev is None or (
            done_at is not None
            and (
                prev[0] is None
                or done_at > prev[0]
                or (done_at == prev[0] and cid > prev[2])
            )
        ):
            best[uid] = (done_at, row.organization_id, cid)

    return {
        uid: _audience_type(has_engagement=True, organization_id=org_id)
        for uid, (_da, org_id, _cid) in best.items()
    }


async def consultation_done_counts(
    db: AsyncSession,
    *,
    done_from: datetime | None,
    done_to: datetime | None,
    all_time: bool,
) -> dict[str, int]:
    audience = await _consultation_done_audience_by_user(
        db,
        done_from=done_from,
        done_to=done_to,
        all_time=all_time,
    )
    return _audience_split_counts(audience)


async def consultation_done_page(
    db: AsyncSession,
    *,
    done_from: datetime | None,
    done_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    audience = await _consultation_done_audience_by_user(
        db,
        done_from=done_from,
        done_to=done_to,
        all_time=all_time,
    )
    return await _people_page_for_audience(
        db,
        audience=audience,
        page=page,
        limit=limit,
        today=today,
        questionnaire_service=questionnaire_service,
    )


def _open_engagement_base_query(
    *,
    start_from: datetime | None,
    start_to: datetime | None,
    all_time: bool,
):
    query = select(Engagement).where(
        Engagement.status.in_(("running", "scheduled")),
    )
    date_clauses = _b2b_start_date_filter(
        start_from=start_from, start_to=start_to, all_time=all_time
    )
    if date_clauses:
        query = query.where(*date_clauses)
    return query


async def open_engagement_counts(
    db: AsyncSession,
    *,
    start_from: datetime | None,
    start_to: datetime | None,
    all_time: bool,
) -> dict[str, int]:
    base = _open_engagement_base_query(
        start_from=start_from, start_to=start_to, all_time=all_time
    )
    rows = (await db.execute(base)).scalars().all()
    b2b = sum(1 for e in rows if e.organization_id is not None)
    b2c = sum(1 for e in rows if e.organization_id is None)
    return {"total": len(rows), "b2b": b2b, "b2c": b2c}


async def open_engagement_page(
    db: AsyncSession,
    *,
    start_from: datetime | None,
    start_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    base = _open_engagement_base_query(
        start_from=start_from, start_to=start_to, all_time=all_time
    )
    rows_all = (
        await db.execute(
            base.order_by(
                Engagement.start_date.asc().nullslast(),
                Engagement.engagement_id.asc(),
            )
        )
    ).scalars().all()
    counts = {
        "total": len(rows_all),
        "b2b": sum(1 for e in rows_all if e.organization_id is not None),
        "b2c": sum(1 for e in rows_all if e.organization_id is None),
    }
    offset = max(0, (page - 1) * limit)
    page_rows = rows_all[offset : offset + limit]

    dx_ids = {
        int(e.diagnostic_package_id)
        for e in page_rows
        if e.diagnostic_package_id is not None
    }
    dx_name_by_id: dict[int, str] = {}
    if dx_ids:
        packages = (
            await db.execute(
                select(DiagnosticPackage).where(
                    DiagnosticPackage.diagnostic_package_id.in_(list(dx_ids))
                )
            )
        ).scalars().all()
        for pkg in packages:
            dx_name_by_id[int(pkg.diagnostic_package_id)] = str(pkg.package_name or "")

    result: list[dict[str, Any]] = []
    for e in page_rows:
        start = e.start_date
        end = e.end_date
        dx_id = e.diagnostic_package_id
        result.append(
            {
                "engagement_id": int(e.engagement_id),
                "engagement_code": str(e.engagement_code or ""),
                "engagement_name": str(e.engagement_name or ""),
                "type": "B2B" if e.organization_id is not None else "B2C",
                "city": str(e.city or ""),
                "package": dx_name_by_id.get(int(dx_id), "") if dx_id is not None else "",
                "start_date": start.isoformat() if start else None,
                "end_date": end.isoformat() if end else None,
            }
        )
    return result, counts


def _tickets_created_at_filter(
    *,
    created_from: datetime | None,
    created_to: datetime | None,
    all_time: bool,
):
    if all_time:
        return []
    clauses = [SupportTicket.created_at.is_not(None)]
    if created_from is not None:
        clauses.append(SupportTicket.created_at >= created_from)
    if created_to is not None:
        clauses.append(SupportTicket.created_at <= created_to)
    return clauses


async def tickets_counts(
    db: AsyncSession,
    *,
    created_from: datetime | None,
    created_to: datetime | None,
    all_time: bool,
) -> dict[str, int]:
    base = select(SupportTicket.status, func.count()).select_from(SupportTicket)
    for clause in _tickets_created_at_filter(
        created_from=created_from, created_to=created_to, all_time=all_time
    ):
        base = base.where(clause)
    rows = (await db.execute(base.group_by(SupportTicket.status))).all()
    open_count = 0
    solved_count = 0
    for status, count in rows:
        key = str(status or "").strip().lower()
        n = int(count or 0)
        if key == "open":
            open_count = n
        elif key in ("resolved", "closed"):
            solved_count += n
    return {
        "open": open_count,
        "solved": solved_count,
        "total": open_count + solved_count,
    }


async def tickets_page(
    db: AsyncSession,
    *,
    created_from: datetime | None,
    created_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counts = await tickets_counts(
        db,
        created_from=created_from,
        created_to=created_to,
        all_time=all_time,
    )
    query = select(SupportTicket).order_by(
        SupportTicket.created_at.desc().nullslast(),
        SupportTicket.ticket_id.desc(),
    )
    for clause in _tickets_created_at_filter(
        created_from=created_from, created_to=created_to, all_time=all_time
    ):
        query = query.where(clause)
    offset = max(0, (page - 1) * limit)
    tickets = (await db.execute(query.offset(offset).limit(limit))).scalars().all()

    user_ids = {int(t.user_id) for t in tickets if t.user_id is not None}
    users_by_id: dict[int, User] = {}
    if user_ids:
        users = (
            await db.execute(select(User).where(User.user_id.in_(list(user_ids))))
        ).scalars().all()
        users_by_id = {int(u.user_id): u for u in users}

    result: list[dict[str, Any]] = []
    for t in tickets:
        user = users_by_id.get(int(t.user_id)) if t.user_id is not None else None
        raised_at = t.created_at
        result.append(
            {
                "ticket_id": int(t.ticket_id),
                "raised_by": {
                    "name": _person_name(
                        getattr(user, "first_name", None) if user else None,
                        getattr(user, "last_name", None) if user else None,
                    )
                    if user
                    else "—",
                    "phone": str(user.phone) if user and user.phone else "",
                },
                "contact": str(t.contact_input or ""),
                "query": str(t.query_text or ""),
                "raised_at": raised_at.isoformat() if raised_at else None,
                "status": str(t.status or ""),
            }
        )
    return result, counts


# ---------------------------------------------------------------------------
# Action Center pending audiences
# ---------------------------------------------------------------------------


async def _upcoming_collections_audience_by_user(
    db: AsyncSession,
    *,
    collection_from: datetime | None,
    collection_to: datetime | None,
    all_time: bool,
    today: date | None = None,
) -> dict[int, str]:
    """Current PBB: not collected, collection_date >= today, period on collection_date."""
    day = today or datetime.now(timezone.utc).date()
    curr_pbb = current_blood_booking_subquery()
    query = (
        select(
            EngagementParticipant.user_id,
            Engagement.organization_id,
            curr_pbb.c.collection_date,
            EngagementParticipant.engagement_participant_id,
        )
        .select_from(curr_pbb)
        .join(
            EngagementParticipant,
            EngagementParticipant.engagement_participant_id
            == curr_pbb.c.engagement_participant_id,
        )
        .join(
            Engagement,
            Engagement.engagement_id == EngagementParticipant.engagement_id,
        )
        .where(
            curr_pbb.c.collected_at.is_(None),
            curr_pbb.c.collection_date.is_not(None),
            curr_pbb.c.collection_date >= day,
        )
    )
    for clause in _date_period_clauses(
        curr_pbb.c.collection_date,
        stamp_from=collection_from,
        stamp_to=collection_to,
        all_time=all_time,
    ):
        query = query.where(clause)

    rows = (await db.execute(query)).all()
    best: dict[int, tuple[date | None, int | None, int]] = {}
    for row in rows:
        uid = int(row.user_id)
        cdate = row.collection_date
        ep_id = int(row.engagement_participant_id)
        prev = best.get(uid)
        if prev is None or (
            cdate is not None
            and (prev[0] is None or cdate > prev[0] or (cdate == prev[0] and ep_id > prev[2]))
        ):
            best[uid] = (cdate, row.organization_id, ep_id)

    return {
        uid: _audience_type(has_engagement=True, organization_id=org_id)
        for uid, (_cd, org_id, _ep) in best.items()
    }


async def upcoming_collections_counts(
    db: AsyncSession,
    *,
    collection_from: datetime | None,
    collection_to: datetime | None,
    all_time: bool,
    today: date | None = None,
) -> dict[str, int]:
    audience = await _upcoming_collections_audience_by_user(
        db,
        collection_from=collection_from,
        collection_to=collection_to,
        all_time=all_time,
        today=today,
    )
    return _audience_split_counts(audience)


async def upcoming_collections_page(
    db: AsyncSession,
    *,
    collection_from: datetime | None,
    collection_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    audience = await _upcoming_collections_audience_by_user(
        db,
        collection_from=collection_from,
        collection_to=collection_to,
        all_time=all_time,
        today=today,
    )
    return await _people_page_for_audience(
        db,
        audience=audience,
        page=page,
        limit=limit,
        today=today,
        questionnaire_service=questionnaire_service,
    )


async def _overdue_collections_audience_by_user(
    db: AsyncSession,
    *,
    collection_from: datetime | None,
    collection_to: datetime | None,
    all_time: bool,
    today: date | None = None,
) -> dict[int, str]:
    """Current PBB: past collection_date, not collected, booking_id empty."""
    day = today or datetime.now(timezone.utc).date()
    curr_pbb = current_blood_booking_subquery()
    query = (
        select(
            EngagementParticipant.user_id,
            Engagement.organization_id,
            curr_pbb.c.collection_date,
            EngagementParticipant.engagement_participant_id,
        )
        .select_from(curr_pbb)
        .join(
            EngagementParticipant,
            EngagementParticipant.engagement_participant_id
            == curr_pbb.c.engagement_participant_id,
        )
        .join(
            Engagement,
            Engagement.engagement_id == EngagementParticipant.engagement_id,
        )
        .where(
            curr_pbb.c.collected_at.is_(None),
            curr_pbb.c.collection_date.is_not(None),
            curr_pbb.c.collection_date < day,
            or_(
                curr_pbb.c.booking_id.is_(None),
                func.btrim(curr_pbb.c.booking_id) == "",
            ),
        )
    )
    for clause in _date_period_clauses(
        curr_pbb.c.collection_date,
        stamp_from=collection_from,
        stamp_to=collection_to,
        all_time=all_time,
    ):
        query = query.where(clause)

    rows = (await db.execute(query)).all()
    best: dict[int, tuple[date | None, int | None, int]] = {}
    for row in rows:
        uid = int(row.user_id)
        cdate = row.collection_date
        ep_id = int(row.engagement_participant_id)
        prev = best.get(uid)
        if prev is None or (
            cdate is not None
            and (prev[0] is None or cdate > prev[0] or (cdate == prev[0] and ep_id > prev[2]))
        ):
            best[uid] = (cdate, row.organization_id, ep_id)

    return {
        uid: _audience_type(has_engagement=True, organization_id=org_id)
        for uid, (_cd, org_id, _ep) in best.items()
    }


async def overdue_collections_counts(
    db: AsyncSession,
    *,
    collection_from: datetime | None,
    collection_to: datetime | None,
    all_time: bool,
    today: date | None = None,
) -> dict[str, int]:
    audience = await _overdue_collections_audience_by_user(
        db,
        collection_from=collection_from,
        collection_to=collection_to,
        all_time=all_time,
        today=today,
    )
    return _audience_split_counts(audience)


async def overdue_collections_page(
    db: AsyncSession,
    *,
    collection_from: datetime | None,
    collection_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    audience = await _overdue_collections_audience_by_user(
        db,
        collection_from=collection_from,
        collection_to=collection_to,
        all_time=all_time,
        today=today,
    )
    return await _people_page_for_audience(
        db,
        audience=audience,
        page=page,
        limit=limit,
        today=today,
        questionnaire_service=questionnaire_service,
    )


async def _questionnaire_pending_audience_by_user(
    db: AsyncSession,
    *,
    assigned_from: datetime | None,
    assigned_to: datetime | None,
    all_time: bool,
    questionnaire_service: Any | None = None,
) -> dict[int, str]:
    """Enrolled users whose supershyft required questionnaire is not complete.

    Period stamp: assessment_instances.assigned_at (null excluded from ranged).
    """
    enroll_q = (
        select(
            EngagementParticipant.user_id,
            EngagementParticipant.engagement_participant_id,
            Engagement.engagement_id,
            Engagement.organization_id,
            Engagement.assessment_package_id,
        )
        .select_from(EngagementParticipant)
        .join(Engagement, Engagement.engagement_id == EngagementParticipant.engagement_id)
    )
    enroll_rows = (await db.execute(enroll_q)).all()
    if not enroll_rows:
        return {}

    user_ids = list({int(r.user_id) for r in enroll_rows})
    engagement_ids = list({int(r.engagement_id) for r in enroll_rows})

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

    package_ids = list(
        {
            int(r.assessment_package_id)
            for r in enroll_rows
            if r.assessment_package_id is not None
        }
    )
    supershyft_cats_by_package: dict[int, list[int]] = {}
    if package_ids:
        cat_rows = (
            await db.execute(
                select(
                    AssessmentPackageCategory.package_id,
                    QuestionnaireCategory.category_id,
                )
                .join(
                    QuestionnaireCategory,
                    QuestionnaireCategory.category_id
                    == AssessmentPackageCategory.category_id,
                )
                .where(AssessmentPackageCategory.package_id.in_(package_ids))
                .where(QuestionnaireCategory.category_of == "supershyft")
            )
        ).all()
        for prow in cat_rows:
            supershyft_cats_by_package.setdefault(int(prow.package_id), []).append(
                int(prow.category_id)
            )

    instance_ids = [int(i.assessment_instance_id) for i in all_inst]
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

    # (user_id, assigned_at, org_id, primary|None, cat_ids, progress)
    candidates: list[
        tuple[
            int,
            datetime | None,
            int | None,
            AssessmentInstance | None,
            list[int],
            dict[int, str],
        ]
    ] = []
    for row in enroll_rows:
        uid = int(row.user_id)
        eng_id = int(row.engagement_id)
        primary = _pick_primary_instance(
            grouped.get((uid, eng_id), []),
            row.assessment_package_id,
        )
        assigned_at = primary.assigned_at if primary is not None else None
        if not _stamp_in_period(
            assigned_at,
            stamp_from=assigned_from,
            stamp_to=assigned_to,
            all_time=all_time,
        ):
            continue
        cat_ids: list[int] = []
        progress_map: dict[int, str] = {}
        if primary is not None:
            pkg_id = int(primary.package_id)
            cat_ids = supershyft_cats_by_package.get(pkg_id, [])
            progress_map = progress_by_instance.get(
                int(primary.assessment_instance_id), {}
            )
        candidates.append(
            (uid, assigned_at, row.organization_id, primary, cat_ids, progress_map)
        )

    pending: list[tuple[int, datetime | None, int | None, int]] = []
    needs_deep: list[
        tuple[
            int,
            datetime | None,
            int | None,
            AssessmentInstance,
            list[int],
            dict[int, str],
        ]
    ] = []

    for uid, assigned_at, org_id, primary, cat_ids, progress_map in candidates:
        if primary is None:
            # Enrolled, no assessment yet → pending (all_time only reaches here)
            pending.append((uid, assigned_at, org_id, 0))
            continue
        iid = int(primary.assessment_instance_id)
        label = _questionnaire_status_label(
            has_engagement=True,
            instance_status=str(primary.status or ""),
            supershyft_category_ids=cat_ids,
            progress_by_category=progress_map,
            all_required_answered=None,
        )
        if label == "completed":
            continue
        if label == "pending" and cat_ids and questionnaire_service is not None:
            # May still be complete via deep required-answer check
            needs_deep.append(
                (uid, assigned_at, org_id, primary, cat_ids, progress_map)
            )
        else:
            pending.append((uid, assigned_at, org_id, iid))

    if needs_deep and questionnaire_service is not None:
        for uid, assigned_at, org_id, primary, cat_ids, progress_map in needs_deep:
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
            if not ok_all:
                pending.append(
                    (uid, assigned_at, org_id, int(primary.assessment_instance_id))
                )

    best: dict[int, tuple[datetime | None, int | None, int]] = {}
    for uid, assigned_at, org_id, instance_id in pending:
        prev = best.get(uid)
        if prev is None:
            best[uid] = (assigned_at, org_id, instance_id)
            continue
        prev_aa, _prev_org, prev_iid = prev
        if assigned_at is not None and (prev_aa is None or assigned_at > prev_aa):
            best[uid] = (assigned_at, org_id, instance_id)
        elif assigned_at == prev_aa and instance_id > prev_iid:
            best[uid] = (assigned_at, org_id, instance_id)

    return {
        uid: _audience_type(has_engagement=True, organization_id=org_id)
        for uid, (_aa, org_id, _iid) in best.items()
    }


async def questionnaire_pending_counts(
    db: AsyncSession,
    *,
    assigned_from: datetime | None,
    assigned_to: datetime | None,
    all_time: bool,
    questionnaire_service: Any | None = None,
) -> dict[str, int]:
    audience = await _questionnaire_pending_audience_by_user(
        db,
        assigned_from=assigned_from,
        assigned_to=assigned_to,
        all_time=all_time,
        questionnaire_service=questionnaire_service,
    )
    return _audience_split_counts(audience)


async def questionnaire_pending_page(
    db: AsyncSession,
    *,
    assigned_from: datetime | None,
    assigned_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    audience = await _questionnaire_pending_audience_by_user(
        db,
        assigned_from=assigned_from,
        assigned_to=assigned_to,
        all_time=all_time,
        questionnaire_service=questionnaire_service,
    )
    return await _people_page_for_audience(
        db,
        audience=audience,
        page=page,
        limit=limit,
        today=today,
        questionnaire_service=questionnaire_service,
    )


async def _blood_reports_pending_audience_by_user(
    db: AsyncSession,
    *,
    collected_from: datetime | None,
    collected_to: datetime | None,
    all_time: bool,
) -> dict[int, str]:
    """Collected but diagnostic_report_url empty; period on collected_at."""
    curr_pbb = current_blood_booking_subquery()
    query = (
        select(
            EngagementParticipant.user_id,
            Engagement.organization_id,
            curr_pbb.c.collected_at,
            EngagementParticipant.engagement_participant_id,
        )
        .select_from(curr_pbb)
        .join(
            EngagementParticipant,
            EngagementParticipant.engagement_participant_id
            == curr_pbb.c.engagement_participant_id,
        )
        .join(
            Engagement,
            Engagement.engagement_id == EngagementParticipant.engagement_id,
        )
        .where(
            curr_pbb.c.collected_at.is_not(None),
            or_(
                curr_pbb.c.diagnostic_report_url.is_(None),
                func.btrim(curr_pbb.c.diagnostic_report_url) == "",
            ),
        )
    )
    for clause in _stamp_period_clauses(
        curr_pbb.c.collected_at,
        stamp_from=collected_from,
        stamp_to=collected_to,
        all_time=all_time,
    ):
        query = query.where(clause)

    rows = (await db.execute(query)).all()
    best: dict[int, tuple[datetime | None, int | None, int]] = {}
    for row in rows:
        uid = int(row.user_id)
        collected_at = row.collected_at
        ep_id = int(row.engagement_participant_id)
        prev = best.get(uid)
        if prev is None or (
            collected_at is not None
            and (
                prev[0] is None
                or collected_at > prev[0]
                or (collected_at == prev[0] and ep_id > prev[2])
            )
        ):
            best[uid] = (collected_at, row.organization_id, ep_id)

    return {
        uid: _audience_type(has_engagement=True, organization_id=org_id)
        for uid, (_ca, org_id, _ep) in best.items()
    }


async def blood_reports_pending_counts(
    db: AsyncSession,
    *,
    collected_from: datetime | None,
    collected_to: datetime | None,
    all_time: bool,
) -> dict[str, int]:
    audience = await _blood_reports_pending_audience_by_user(
        db,
        collected_from=collected_from,
        collected_to=collected_to,
        all_time=all_time,
    )
    return _audience_split_counts(audience)


async def blood_reports_pending_page(
    db: AsyncSession,
    *,
    collected_from: datetime | None,
    collected_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    audience = await _blood_reports_pending_audience_by_user(
        db,
        collected_from=collected_from,
        collected_to=collected_to,
        all_time=all_time,
    )
    return await _people_page_for_audience(
        db,
        audience=audience,
        page=page,
        limit=limit,
        today=today,
        questionnaire_service=questionnaire_service,
    )


async def _is_questionnaire_complete_for_instance(
    *,
    uid: int,
    primary: AssessmentInstance,
    cat_ids: list[int],
    progress_map: dict[int, str],
    questionnaire_service: Any | None,
    db: AsyncSession,
) -> bool:
    label = _questionnaire_status_label(
        has_engagement=True,
        instance_status=str(primary.status or ""),
        supershyft_category_ids=cat_ids,
        progress_by_category=progress_map,
        all_required_answered=None,
    )
    if label == "completed":
        return True
    if not cat_ids or questionnaire_service is None:
        return False
    try:
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
                return False
        return True
    except Exception:
        return False


async def _bio_ai_pending_audience_by_user(
    db: AsyncSession,
    *,
    stamp_from: datetime | None,
    stamp_to: datetime | None,
    all_time: bool,
    questionnaire_service: Any | None = None,
) -> dict[int, str]:
    """Blood report loaded + questionnaire done + BioAI report_url empty/missing.

    Period stamp: coalesce(IHR.created_at, assessment.completed_at).
    """
    curr_pbb = current_blood_booking_subquery()
    blood_q = (
        select(
            EngagementParticipant.user_id,
            EngagementParticipant.engagement_participant_id,
            Engagement.engagement_id,
            Engagement.organization_id,
            Engagement.assessment_package_id,
        )
        .select_from(curr_pbb)
        .join(
            EngagementParticipant,
            EngagementParticipant.engagement_participant_id
            == curr_pbb.c.engagement_participant_id,
        )
        .join(
            Engagement,
            Engagement.engagement_id == EngagementParticipant.engagement_id,
        )
        .where(
            curr_pbb.c.diagnostic_report_url.is_not(None),
            func.btrim(curr_pbb.c.diagnostic_report_url) != "",
        )
    )
    blood_rows = (await db.execute(blood_q)).all()
    if not blood_rows:
        return {}

    user_ids = list({int(r.user_id) for r in blood_rows})
    engagement_ids = list({int(r.engagement_id) for r in blood_rows})

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

    package_ids = list(
        {
            int(r.assessment_package_id)
            for r in blood_rows
            if r.assessment_package_id is not None
        }
    )
    supershyft_cats_by_package: dict[int, list[int]] = {}
    if package_ids:
        cat_rows = (
            await db.execute(
                select(
                    AssessmentPackageCategory.package_id,
                    QuestionnaireCategory.category_id,
                )
                .join(
                    QuestionnaireCategory,
                    QuestionnaireCategory.category_id
                    == AssessmentPackageCategory.category_id,
                )
                .where(AssessmentPackageCategory.package_id.in_(package_ids))
                .where(QuestionnaireCategory.category_of == "supershyft")
            )
        ).all()
        for prow in cat_rows:
            supershyft_cats_by_package.setdefault(int(prow.package_id), []).append(
                int(prow.category_id)
            )

    instance_ids = [int(i.assessment_instance_id) for i in all_inst]
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

    ihr_rows = (
        await db.execute(
            select(IndividualHealthReport).where(
                IndividualHealthReport.user_id.in_(user_ids),
                or_(
                    IndividualHealthReport.engagement_id.in_(engagement_ids),
                    IndividualHealthReport.engagement_id.is_(None),
                ),
            )
        )
    ).scalars().all()
    # Prefer IHR matching engagement; key by (user_id, engagement_id)
    ihr_by_user_eng: dict[tuple[int, int], IndividualHealthReport] = {}
    ihr_by_user: dict[int, IndividualHealthReport] = {}
    for ihr in ihr_rows:
        uid = int(ihr.user_id)
        eng = int(ihr.engagement_id) if ihr.engagement_id is not None else None
        if eng is not None:
            prev = ihr_by_user_eng.get((uid, eng))
            if prev is None or int(ihr.report_id) > int(prev.report_id):
                ihr_by_user_eng[(uid, eng)] = ihr
        prev_u = ihr_by_user.get(uid)
        if prev_u is None or int(ihr.report_id) > int(prev_u.report_id):
            ihr_by_user[uid] = ihr

    best: dict[int, tuple[datetime | None, int | None, int]] = {}
    for row in blood_rows:
        uid = int(row.user_id)
        eng_id = int(row.engagement_id)
        ep_id = int(row.engagement_participant_id)
        primary = _pick_primary_instance(
            grouped.get((uid, eng_id), []),
            row.assessment_package_id,
        )
        if primary is None:
            continue
        cat_ids = supershyft_cats_by_package.get(int(primary.package_id), [])
        progress_map = progress_by_instance.get(
            int(primary.assessment_instance_id), {}
        )
        q_done = await _is_questionnaire_complete_for_instance(
            uid=uid,
            primary=primary,
            cat_ids=cat_ids,
            progress_map=progress_map,
            questionnaire_service=questionnaire_service,
            db=db,
        )
        if not q_done:
            continue

        ihr = ihr_by_user_eng.get((uid, eng_id)) or ihr_by_user.get(uid)
        report_url = str(ihr.report_url or "").strip() if ihr is not None else ""
        if report_url:
            continue

        stamp = None
        if ihr is not None and ihr.created_at is not None:
            stamp = ihr.created_at
        elif primary.completed_at is not None:
            stamp = primary.completed_at
        if not _stamp_in_period(
            stamp,
            stamp_from=stamp_from,
            stamp_to=stamp_to,
            all_time=all_time,
        ):
            continue

        prev = best.get(uid)
        if prev is None or (
            stamp is not None
            and (prev[0] is None or stamp > prev[0] or (stamp == prev[0] and ep_id > prev[2]))
        ):
            best[uid] = (stamp, row.organization_id, ep_id)

    return {
        uid: _audience_type(has_engagement=True, organization_id=org_id)
        for uid, (_st, org_id, _ep) in best.items()
    }


async def bio_ai_pending_counts(
    db: AsyncSession,
    *,
    stamp_from: datetime | None,
    stamp_to: datetime | None,
    all_time: bool,
    questionnaire_service: Any | None = None,
) -> dict[str, int]:
    audience = await _bio_ai_pending_audience_by_user(
        db,
        stamp_from=stamp_from,
        stamp_to=stamp_to,
        all_time=all_time,
        questionnaire_service=questionnaire_service,
    )
    return _audience_split_counts(audience)


async def bio_ai_pending_page(
    db: AsyncSession,
    *,
    stamp_from: datetime | None,
    stamp_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    audience = await _bio_ai_pending_audience_by_user(
        db,
        stamp_from=stamp_from,
        stamp_to=stamp_to,
        all_time=all_time,
        questionnaire_service=questionnaire_service,
    )
    return await _people_page_for_audience(
        db,
        audience=audience,
        page=page,
        limit=limit,
        today=today,
        questionnaire_service=questionnaire_service,
    )


async def _consultation_pending_audience_by_user(
    db: AsyncSession,
    *,
    created_from: datetime | None,
    created_to: datetime | None,
    all_time: bool,
) -> dict[int, str]:
    """want=true AND done=false; period on consultation_bookings.created_at."""
    query = (
        select(
            EngagementParticipant.user_id,
            Engagement.organization_id,
            ConsultationBooking.created_at,
            ConsultationBooking.consultation_id,
        )
        .select_from(ConsultationBooking)
        .join(
            EngagementParticipant,
            EngagementParticipant.engagement_participant_id
            == ConsultationBooking.engagement_participant_id,
        )
        .join(
            Engagement,
            Engagement.engagement_id == EngagementParticipant.engagement_id,
        )
        .where(
            ConsultationBooking.want.is_(True),
            ConsultationBooking.done.is_(False),
        )
    )
    for clause in _stamp_period_clauses(
        ConsultationBooking.created_at,
        stamp_from=created_from,
        stamp_to=created_to,
        all_time=all_time,
    ):
        query = query.where(clause)

    rows = (await db.execute(query)).all()
    best: dict[int, tuple[datetime | None, int | None, int]] = {}
    for row in rows:
        uid = int(row.user_id)
        created_at = row.created_at
        cid = int(row.consultation_id)
        prev = best.get(uid)
        if prev is None or (
            created_at is not None
            and (
                prev[0] is None
                or created_at > prev[0]
                or (created_at == prev[0] and cid > prev[2])
            )
        ):
            best[uid] = (created_at, row.organization_id, cid)

    return {
        uid: _audience_type(has_engagement=True, organization_id=org_id)
        for uid, (_ca, org_id, _cid) in best.items()
    }


async def consultation_pending_counts(
    db: AsyncSession,
    *,
    created_from: datetime | None,
    created_to: datetime | None,
    all_time: bool,
) -> dict[str, int]:
    audience = await _consultation_pending_audience_by_user(
        db,
        created_from=created_from,
        created_to=created_to,
        all_time=all_time,
    )
    return _audience_split_counts(audience)


async def consultation_pending_page(
    db: AsyncSession,
    *,
    created_from: datetime | None,
    created_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    audience = await _consultation_pending_audience_by_user(
        db,
        created_from=created_from,
        created_to=created_to,
        all_time=all_time,
    )
    return await _people_page_for_audience(
        db,
        audience=audience,
        page=page,
        limit=limit,
        today=today,
        questionnaire_service=questionnaire_service,
    )
