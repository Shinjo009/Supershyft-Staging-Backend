"""B2C-scoped command-center metrics for the admin dashboard."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.dashboard.command_period import command_today
from modules.dashboard.command_service import (
    _build_people_rows,
    _date_period_clauses,
    _person_name,
    _stamp_period_clauses,
)
from modules.diagnostics.models import DiagnosticPackage
from modules.discounts.models import DiscountCode, DiscountUsage
from modules.engagements.blood_bookings_repository import current_blood_booking_subquery
from modules.engagements.models import Engagement, EngagementParticipant
from modules.experts.models import ConsultationBooking
from modules.reports.models import IndividualHealthReport
from modules.users.models import User

B2C_BOOKING_STATUSES = ("scheduled", "running", "completed")


def _b2c_engagement_clause():
    return Engagement.organization_id.is_(None)


def _filter_b2c_audience(audience: dict[int, str]) -> dict[int, str]:
    return {uid: a for uid, a in audience.items() if a == "B2C"}


async def _page_b2c_users(
    db: AsyncSession,
    *,
    user_ids: list[int],
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], int]:
    total = len(user_ids)
    offset = max(0, (page - 1) * limit)
    page_ids = user_ids[offset : offset + limit]
    if not page_ids:
        return [], total

    users = (
        await db.execute(
            select(User).where(User.user_id.in_(page_ids)).order_by(User.user_id.desc())
        )
    ).scalars().all()
    by_id = {int(u.user_id): u for u in users}
    ordered = [by_id[uid] for uid in page_ids if uid in by_id]
    rows = await _build_people_rows(
        db,
        users=ordered,
        user_ids=[int(u.user_id) for u in ordered],
        today=today or command_today(),
        questionnaire_service=questionnaire_service,
    )
    return rows, total


async def _total_bookings_user_ids(
    db: AsyncSession,
    *,
    created_from: datetime | None,
    created_to: datetime | None,
    all_time: bool,
) -> list[int]:
    """Distinct B2C users with an engagement in scheduled/running/completed.

    Period filter uses users.created_at (null excluded unless all_time).
    """
    query = (
        select(User.user_id)
        .select_from(EngagementParticipant)
        .join(Engagement, Engagement.engagement_id == EngagementParticipant.engagement_id)
        .join(User, User.user_id == EngagementParticipant.user_id)
        .where(
            _b2c_engagement_clause(),
            Engagement.status.in_(B2C_BOOKING_STATUSES),
        )
        .distinct()
    )
    for clause in _stamp_period_clauses(
        User.created_at,
        stamp_from=created_from,
        stamp_to=created_to,
        all_time=all_time,
    ):
        query = query.where(clause)

    rows = (await db.execute(query.order_by(User.user_id.desc()))).all()
    return [int(r.user_id) for r in rows]


async def b2c_total_bookings_count(
    db: AsyncSession,
    *,
    created_from: datetime | None,
    created_to: datetime | None,
    all_time: bool,
) -> int:
    ids = await _total_bookings_user_ids(
        db,
        created_from=created_from,
        created_to=created_to,
        all_time=all_time,
    )
    return len(ids)


async def b2c_total_bookings_page(
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
    ids = await _total_bookings_user_ids(
        db,
        created_from=created_from,
        created_to=created_to,
        all_time=all_time,
    )
    return await _page_b2c_users(
        db,
        user_ids=ids,
        page=page,
        limit=limit,
        today=today,
        questionnaire_service=questionnaire_service,
    )


async def _collection_tomorrow_user_ids(
    db: AsyncSession,
    *,
    collection_from: datetime | None,
    collection_to: datetime | None,
    all_time: bool,
    today: date | None = None,
) -> list[int]:
    day = today or command_today()
    tomorrow = day + timedelta(days=1)
    curr_pbb = current_blood_booking_subquery()
    query = (
        select(
            EngagementParticipant.user_id,
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
            _b2c_engagement_clause(),
            curr_pbb.c.collection_date == tomorrow,
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
    best: dict[int, tuple[date | None, int]] = {}
    for row in rows:
        uid = int(row.user_id)
        cdate = row.collection_date
        ep_id = int(row.engagement_participant_id)
        prev = best.get(uid)
        if prev is None or (
            cdate is not None
            and (prev[0] is None or cdate > prev[0] or (cdate == prev[0] and ep_id > prev[1]))
        ):
            best[uid] = (cdate, ep_id)
    return sorted(best.keys(), reverse=True)


async def b2c_collection_tomorrow_count(
    db: AsyncSession,
    *,
    collection_from: datetime | None,
    collection_to: datetime | None,
    all_time: bool,
    today: date | None = None,
) -> int:
    ids = await _collection_tomorrow_user_ids(
        db,
        collection_from=collection_from,
        collection_to=collection_to,
        all_time=all_time,
        today=today,
    )
    return len(ids)


async def b2c_collection_tomorrow_page(
    db: AsyncSession,
    *,
    collection_from: datetime | None,
    collection_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], int]:
    ids = await _collection_tomorrow_user_ids(
        db,
        collection_from=collection_from,
        collection_to=collection_to,
        all_time=all_time,
        today=today,
    )
    return await _page_b2c_users(
        db,
        user_ids=ids,
        page=page,
        limit=limit,
        today=today,
        questionnaire_service=questionnaire_service,
    )


async def b2c_tomorrows_collection_list(
    db: AsyncSession,
    *,
    collection_from: datetime | None,
    collection_to: datetime | None,
    all_time: bool,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Inline panel rows: collection_time, name, phone, address/city/pincode."""
    day = today or command_today()
    tomorrow = day + timedelta(days=1)
    curr_pbb = current_blood_booking_subquery()
    query = (
        select(
            EngagementParticipant.user_id,
            EngagementParticipant.engagement_participant_id,
            EngagementParticipant.address,
            EngagementParticipant.city,
            EngagementParticipant.pincode,
            User.first_name,
            User.last_name,
            User.phone,
            User.address.label("user_address"),
            User.city.label("user_city"),
            User.pin_code.label("user_pincode"),
            curr_pbb.c.collection_time,
            curr_pbb.c.collection_date,
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
        .join(User, User.user_id == EngagementParticipant.user_id)
        .where(
            _b2c_engagement_clause(),
            curr_pbb.c.collection_date == tomorrow,
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
    best: dict[int, Any] = {}
    for row in rows:
        uid = int(row.user_id)
        ep_id = int(row.engagement_participant_id)
        prev = best.get(uid)
        if prev is None or ep_id > int(prev.engagement_participant_id):
            best[uid] = row

    out: list[dict[str, Any]] = []
    for uid in sorted(best.keys(), reverse=True):
        row = best[uid]
        address = (row.address or row.user_address or "").strip()
        city = (row.city or row.user_city or "").strip()
        pincode = (row.pincode or row.user_pincode or "").strip()
        parts = [p for p in (address, city, pincode) if p]
        ctime = row.collection_time
        out.append(
            {
                "user_id": uid,
                "collection_time": str(ctime) if ctime is not None else "",
                "name": _person_name(row.first_name, row.last_name),
                "phone": row.phone or "",
                "address": ", ".join(parts),
            }
        )
    out.sort(key=lambda r: (r["collection_time"] or "99:99", r["name"]))
    return out


async def _tests_completed_b2c_user_ids(
    db: AsyncSession,
    *,
    collected_from: datetime | None,
    collected_to: datetime | None,
    all_time: bool,
) -> list[int]:
    curr_pbb = current_blood_booking_subquery()
    query = (
        select(
            EngagementParticipant.user_id,
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
            _b2c_engagement_clause(),
            curr_pbb.c.collected_at.is_not(None),
        )
    )
    if not all_time:
        if collected_from is not None:
            query = query.where(curr_pbb.c.collected_at >= collected_from)
        if collected_to is not None:
            query = query.where(curr_pbb.c.collected_at <= collected_to)

    rows = (await db.execute(query)).all()
    best: dict[int, tuple[datetime | None, int]] = {}
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
                or (collected_at == prev[0] and ep_id > prev[1])
            )
        ):
            best[uid] = (collected_at, ep_id)
    return sorted(best.keys(), reverse=True)


async def b2c_tests_completed_count(
    db: AsyncSession,
    *,
    collected_from: datetime | None,
    collected_to: datetime | None,
    all_time: bool,
) -> int:
    return len(
        await _tests_completed_b2c_user_ids(
            db,
            collected_from=collected_from,
            collected_to=collected_to,
            all_time=all_time,
        )
    )


async def b2c_tests_completed_page(
    db: AsyncSession,
    *,
    collected_from: datetime | None,
    collected_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], int]:
    ids = await _tests_completed_b2c_user_ids(
        db,
        collected_from=collected_from,
        collected_to=collected_to,
        all_time=all_time,
    )
    return await _page_b2c_users(
        db,
        user_ids=ids,
        page=page,
        limit=limit,
        today=today,
        questionnaire_service=questionnaire_service,
    )


async def _bioai_b2c_user_ids(
    db: AsyncSession,
    *,
    received_from: datetime | None,
    received_to: datetime | None,
    all_time: bool,
) -> list[int]:
    """B2C users with BioAI report_url; period on IHR.report_received_at.

    Spec referred to blood_bookings.received_at; schema uses report_received_at
    on individual_health_report (same stamp used by overview BioAI KPI).
    """
    query = (
        select(
            IndividualHealthReport.user_id,
            IndividualHealthReport.report_received_at,
            IndividualHealthReport.report_id,
        )
        .select_from(IndividualHealthReport)
        .join(
            Engagement,
            Engagement.engagement_id == IndividualHealthReport.engagement_id,
        )
        .where(
            _b2c_engagement_clause(),
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
    best: dict[int, tuple[datetime | None, int]] = {}
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
                or (received_at == prev[0] and report_id > prev[1])
            )
        ):
            best[uid] = (received_at, report_id)
    return sorted(best.keys(), reverse=True)


async def b2c_bioai_reports_count(
    db: AsyncSession,
    *,
    received_from: datetime | None,
    received_to: datetime | None,
    all_time: bool,
) -> int:
    return len(
        await _bioai_b2c_user_ids(
            db,
            received_from=received_from,
            received_to=received_to,
            all_time=all_time,
        )
    )


async def b2c_bioai_reports_page(
    db: AsyncSession,
    *,
    received_from: datetime | None,
    received_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], int]:
    ids = await _bioai_b2c_user_ids(
        db,
        received_from=received_from,
        received_to=received_to,
        all_time=all_time,
    )
    return await _page_b2c_users(
        db,
        user_ids=ids,
        page=page,
        limit=limit,
        today=today,
        questionnaire_service=questionnaire_service,
    )


async def _consultation_done_b2c_user_ids(
    db: AsyncSession,
    *,
    done_from: datetime | None,
    done_to: datetime | None,
    all_time: bool,
) -> list[int]:
    query = (
        select(
            EngagementParticipant.user_id,
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
        .where(
            _b2c_engagement_clause(),
            ConsultationBooking.done.is_(True),
        )
    )
    for clause in _stamp_period_clauses(
        ConsultationBooking.consultation_done_at,
        stamp_from=done_from,
        stamp_to=done_to,
        all_time=all_time,
    ):
        query = query.where(clause)

    rows = (await db.execute(query)).all()
    best: dict[int, tuple[datetime | None, int]] = {}
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
                or (done_at == prev[0] and cid > prev[1])
            )
        ):
            best[uid] = (done_at, cid)
    return sorted(best.keys(), reverse=True)


async def b2c_consultation_done_count(
    db: AsyncSession,
    *,
    done_from: datetime | None,
    done_to: datetime | None,
    all_time: bool,
) -> int:
    return len(
        await _consultation_done_b2c_user_ids(
            db,
            done_from=done_from,
            done_to=done_to,
            all_time=all_time,
        )
    )


async def b2c_consultation_done_page(
    db: AsyncSession,
    *,
    done_from: datetime | None,
    done_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], int]:
    ids = await _consultation_done_b2c_user_ids(
        db,
        done_from=done_from,
        done_to=done_to,
        all_time=all_time,
    )
    return await _page_b2c_users(
        db,
        user_ids=ids,
        page=page,
        limit=limit,
        today=today,
        questionnaire_service=questionnaire_service,
    )


def _resolve_dx_package_id(row: Any) -> int | None:
    gender = str(getattr(row, "gender", None) or "").lower()
    dx_id = getattr(row, "diagnostic_package_id", None)
    if dx_id is not None:
        return int(dx_id)
    female = getattr(row, "diagnostic_package_id_female", None)
    male = getattr(row, "diagnostic_package_id_male", None)
    if gender == "female" and female is not None:
        return int(female)
    if gender == "male" and male is not None:
        return int(male)
    if male is not None:
        return int(male)
    if female is not None:
        return int(female)
    return None


async def b2c_package_performance(
    db: AsyncSession,
    *,
    created_from: datetime | None,
    created_to: datetime | None,
    all_time: bool,
) -> list[dict[str, Any]]:
    """Package name + distinct B2C user counts in period (users.created_at)."""
    query = (
        select(
            EngagementParticipant.user_id,
            User.gender,
            User.created_at,
            Engagement.diagnostic_package_id,
            Engagement.diagnostic_package_id_male,
            Engagement.diagnostic_package_id_female,
        )
        .select_from(EngagementParticipant)
        .join(Engagement, Engagement.engagement_id == EngagementParticipant.engagement_id)
        .join(User, User.user_id == EngagementParticipant.user_id)
        .where(
            _b2c_engagement_clause(),
            Engagement.status.in_(B2C_BOOKING_STATUSES),
            or_(
                Engagement.diagnostic_package_id.is_not(None),
                Engagement.diagnostic_package_id_male.is_not(None),
                Engagement.diagnostic_package_id_female.is_not(None),
            ),
        )
    )
    for clause in _stamp_period_clauses(
        User.created_at,
        stamp_from=created_from,
        stamp_to=created_to,
        all_time=all_time,
    ):
        query = query.where(clause)

    rows = (await db.execute(query)).all()
    users_by_pkg: dict[int, set[int]] = {}
    for row in rows:
        pkg_id = _resolve_dx_package_id(row)
        if pkg_id is None:
            continue
        users_by_pkg.setdefault(pkg_id, set()).add(int(row.user_id))

    if not users_by_pkg:
        return []

    pkgs = (
        await db.execute(
            select(DiagnosticPackage).where(
                DiagnosticPackage.diagnostic_package_id.in_(list(users_by_pkg.keys()))
            )
        )
    ).scalars().all()
    name_by_id = {
        int(p.diagnostic_package_id): str(p.package_name or "") for p in pkgs
    }

    result = [
        {
            "package_id": pkg_id,
            "package_name": name_by_id.get(pkg_id, f"Package {pkg_id}"),
            "user_count": len(uids),
        }
        for pkg_id, uids in users_by_pkg.items()
    ]
    result.sort(key=lambda r: (-r["user_count"], r["package_name"]))
    return result


async def b2c_package_users_page(
    db: AsyncSession,
    *,
    package_id: int,
    created_from: datetime | None,
    created_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], int]:
    query = (
        select(
            EngagementParticipant.user_id,
            User.gender,
            Engagement.diagnostic_package_id,
            Engagement.diagnostic_package_id_male,
            Engagement.diagnostic_package_id_female,
        )
        .select_from(EngagementParticipant)
        .join(Engagement, Engagement.engagement_id == EngagementParticipant.engagement_id)
        .join(User, User.user_id == EngagementParticipant.user_id)
        .where(
            _b2c_engagement_clause(),
            Engagement.status.in_(B2C_BOOKING_STATUSES),
        )
    )
    for clause in _stamp_period_clauses(
        User.created_at,
        stamp_from=created_from,
        stamp_to=created_to,
        all_time=all_time,
    ):
        query = query.where(clause)

    rows = (await db.execute(query)).all()
    user_ids: set[int] = set()
    for row in rows:
        resolved = _resolve_dx_package_id(row)
        if resolved == int(package_id):
            user_ids.add(int(row.user_id))
    return await _page_b2c_users(
        db,
        user_ids=sorted(user_ids, reverse=True),
        page=page,
        limit=limit,
        today=today,
        questionnaire_service=questionnaire_service,
    )


async def b2c_coupon_usage(
    db: AsyncSession,
    *,
    created_from: datetime | None,
    created_to: datetime | None,
    all_time: bool,
) -> list[dict[str, Any]]:
    """Discount codes with distinct B2C user redemption counts."""
    query = (
        select(
            DiscountUsage.discount_code_id,
            DiscountUsage.user_id,
            DiscountCode.code,
            DiscountUsage.created_at,
        )
        .select_from(DiscountUsage)
        .join(
            DiscountCode,
            DiscountCode.discount_code_id == DiscountUsage.discount_code_id,
        )
        .outerjoin(Engagement, Engagement.engagement_id == DiscountUsage.engagement_id)
        .where(
            DiscountUsage.status == "committed",
            or_(
                DiscountUsage.organization_id.is_(None),
                Engagement.organization_id.is_(None),
            ),
        )
    )
    for clause in _stamp_period_clauses(
        DiscountUsage.created_at,
        stamp_from=created_from,
        stamp_to=created_to,
        all_time=all_time,
    ):
        query = query.where(clause)

    rows = (await db.execute(query)).all()
    by_code: dict[int, dict[str, Any]] = {}
    for row in rows:
        code_id = int(row.discount_code_id)
        entry = by_code.setdefault(
            code_id,
            {"discount_code_id": code_id, "discount_code": str(row.code or ""), "users": set()},
        )
        entry["users"].add(int(row.user_id))

    result = [
        {
            "discount_code_id": v["discount_code_id"],
            "discount_code": v["discount_code"],
            "user_count": len(v["users"]),
        }
        for v in by_code.values()
    ]
    result.sort(key=lambda r: (-r["user_count"], r["discount_code"]))
    return result


async def b2c_coupon_users_page(
    db: AsyncSession,
    *,
    discount_code_id: int,
    created_from: datetime | None,
    created_to: datetime | None,
    all_time: bool,
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], int]:
    query = (
        select(DiscountUsage.user_id)
        .select_from(DiscountUsage)
        .outerjoin(Engagement, Engagement.engagement_id == DiscountUsage.engagement_id)
        .where(
            DiscountUsage.discount_code_id == int(discount_code_id),
            DiscountUsage.status == "committed",
            or_(
                DiscountUsage.organization_id.is_(None),
                Engagement.organization_id.is_(None),
            ),
        )
        .distinct()
    )
    for clause in _stamp_period_clauses(
        DiscountUsage.created_at,
        stamp_from=created_from,
        stamp_to=created_to,
        all_time=all_time,
    ):
        query = query.where(clause)

    rows = (await db.execute(query.order_by(DiscountUsage.user_id.desc()))).all()
    ids = [int(r.user_id) for r in rows]
    return await _page_b2c_users(
        db,
        user_ids=ids,
        page=page,
        limit=limit,
        today=today,
        questionnaire_service=questionnaire_service,
    )


async def b2c_users_page(
    db: AsyncSession,
    *,
    page: int,
    limit: int,
    today: date | None = None,
    questionnaire_service: Any | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """All B2C users (org_id null engagements); no timeline filter."""
    query = (
        select(EngagementParticipant.user_id)
        .select_from(EngagementParticipant)
        .join(Engagement, Engagement.engagement_id == EngagementParticipant.engagement_id)
        .where(_b2c_engagement_clause())
        .distinct()
    )
    rows = (await db.execute(query.order_by(EngagementParticipant.user_id.desc()))).all()
    ids = [int(r.user_id) for r in rows]
    return await _page_b2c_users(
        db,
        user_ids=ids,
        page=page,
        limit=limit,
        today=today,
        questionnaire_service=questionnaire_service,
    )


async def b2c_summary_counts(
    db: AsyncSession,
    *,
    start_from: datetime | None,
    start_to: datetime | None,
    all_time: bool,
    today: date | None = None,
) -> dict[str, Any]:
    day = today or command_today()
    total_bookings = await b2c_total_bookings_count(
        db, created_from=start_from, created_to=start_to, all_time=all_time
    )
    collection_tomorrow = await b2c_collection_tomorrow_count(
        db,
        collection_from=start_from,
        collection_to=start_to,
        all_time=all_time,
        today=day,
    )
    tests_completed = await b2c_tests_completed_count(
        db, collected_from=start_from, collected_to=start_to, all_time=all_time
    )
    bio_ai_reports = await b2c_bioai_reports_count(
        db, received_from=start_from, received_to=start_to, all_time=all_time
    )
    consultation_done = await b2c_consultation_done_count(
        db, done_from=start_from, done_to=start_to, all_time=all_time
    )
    packages = await b2c_package_performance(
        db, created_from=start_from, created_to=start_to, all_time=all_time
    )
    coupons = await b2c_coupon_usage(
        db, created_from=start_from, created_to=start_to, all_time=all_time
    )
    tomorrow_list = await b2c_tomorrows_collection_list(
        db,
        collection_from=start_from,
        collection_to=start_to,
        all_time=all_time,
        today=day,
    )
    return {
        "total_bookings": total_bookings,
        "collection_tomorrow": collection_tomorrow,
        "tests_completed": tests_completed,
        "bio_ai_reports": bio_ai_reports,
        "consultation_done": consultation_done,
        "packages": packages,
        "coupons": coupons,
        "tomorrows_collection": tomorrow_list,
    }

