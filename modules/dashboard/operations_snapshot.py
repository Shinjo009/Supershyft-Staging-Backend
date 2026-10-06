"""Action Center operational rows for GET /admin/dashboard/overview."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.audit.dependencies import get_audit_service
from modules.employee.service import EmployeeContext
from modules.engagements.dependencies import get_engagements_service
from modules.engagements.models import Engagement
from modules.notifications.dependencies import get_notifications_service
from modules.organizations.dependencies import get_organizations_service
from modules.users.models import User

ACTIVE_STATUSES = ("running", "scheduled")
PAGE_SIZE = 100
PENDING_PAYMENT_THRESHOLD_MINUTES = 15


def _today_iso() -> str:
    return date.today().isoformat()


def _week_range_local() -> tuple[str, str]:
    today = date.today()
    monday_offset = -6 if today.weekday() == 6 else -today.weekday()
    start = today + timedelta(days=monday_offset)
    end = start + timedelta(days=6)
    return start.isoformat(), end.isoformat()


def _date_part(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _ranges_overlap(start: Any, end: Any, range_start: str, range_end: str) -> bool:
    start_date = _date_part(start)
    end_date = _date_part(end)
    if not start_date or not end_date:
        return False
    return start_date <= range_end and end_date >= range_start


def _keep_active(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        status = (row.get("status") or "").lower()
        if status in ACTIVE_STATUSES:
            out.append(row)
    return out


def _pending_minutes(booked_at: str | datetime | None) -> int | None:
    if booked_at is None:
        return None
    if isinstance(booked_at, datetime):
        timestamp = booked_at.timestamp()
    else:
        try:
            timestamp = datetime.fromisoformat(str(booked_at).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    now = datetime.now(timezone.utc).timestamp()
    return int((now - timestamp) // 60)


def _serviceability_row(log: dict, user_names: dict[int, str], engagement_names: dict[int, str]) -> dict:
    request = log.get("request_payload") if isinstance(log.get("request_payload"), dict) else {}
    response = log.get("response_payload") if isinstance(log.get("response_payload"), dict) else {}

    def field(key: str) -> str | None:
        val = request.get(key)
        if val is None:
            return None
        text = str(val).strip()
        return text or None

    zipcode = field("zipcode")
    lat = field("lat")
    lng = field("long") or field("lng")
    location_parts = []
    if zipcode:
        location_parts.append(f"Pin {zipcode}")
    if lat and lng:
        location_parts.append(f"{lat}, {lng}")

    issue_message = (log.get("error_message") or "").strip()
    if not issue_message:
        msg = response.get("message")
        issue_message = str(msg).strip() if msg else "Location is not serviceable"

    user_id = log.get("user_id")
    engagement_id = log.get("engagement_id")
    participant_label = "—"
    if user_id is not None:
        uid = int(user_id)
        participant_label = user_names.get(uid) or f"User #{uid}"
    engagement_label = "—"
    if engagement_id is not None:
        eid = int(engagement_id)
        engagement_label = engagement_names.get(eid) or f"#{eid}"

    created = log.get("created_at")
    failed_at = created.isoformat() if hasattr(created, "isoformat") else created

    return {
        "sync_log_id": log.get("sync_log_id"),
        "user_id": user_id,
        "engagement_id": engagement_id,
        "participant_label": participant_label,
        "location_label": " · ".join(location_parts) if location_parts else "—",
        "issue_message": issue_message,
        "engagement_label": engagement_label,
        "failed_at": failed_at,
    }


async def _engagement_rows_for_list(
    db: AsyncSession,
    *,
    employee: EmployeeContext,
    engagements_service,
    on_date: date | None,
) -> tuple[list[dict], bool]:
    from modules.engagements.router import _engagement_to_dict
    status_filter = "running,scheduled"
    engagements, total, readiness_by_id, counts_by_id = await engagements_service.list_engagements_for_employee(
        db,
        employee=employee,
        page=1,
        limit=PAGE_SIZE,
        organization_id=None,
        camp_no=None,
        status=status_filter,
        city=None,
        on_date=on_date,
        search=None,
        engagement_type=None,
        audience=None,
        sort_by="start_date",
        sort_dir="asc",
    )
    slot_details_map = await engagements_service.resolve_slot_details_map(db, engagements)
    rows = [
        _engagement_to_dict(
            engagement,
            readiness=readiness_by_id[engagement.engagement_id],
            participant_count=counts_by_id.get(int(engagement.engagement_id), 0),
            slot_detail=(
                slot_details_map.get(int(engagement.slot_detail_id))
                if engagement.slot_detail_id is not None
                else None
            ),
        )
        for engagement in engagements
    ]
    truncated = total > len(rows)
    return rows, truncated


async def _org_names_map(
    db: AsyncSession,
    *,
    employee: EmployeeContext,
    organizations_service,
) -> dict[int, str]:
    orgs, _total = await organizations_service.list_organizations_for_employee(
        db,
        employee=employee,
        page=1,
        limit=100,
        search=None,
        status=None,
        organization_type=None,
        bd_employee_id=None,
        city=None,
        country=None,
        industry_key=None,
        sort_by=None,
        sort_dir=None,
    )
    return {int(org.organization_id): org.name for org in orgs if org.name}


async def _hydrate_serviceability_labels(
    db: AsyncSession,
    logs: list[dict],
) -> list[dict]:
    user_ids = {int(log["user_id"]) for log in logs if log.get("user_id") is not None}
    engagement_ids = {int(log["engagement_id"]) for log in logs if log.get("engagement_id") is not None}

    user_names: dict[int, str] = {}
    if user_ids:
        result = await db.execute(
            select(User.user_id, User.first_name, User.last_name).where(User.user_id.in_(user_ids))
        )
        for uid, first, last in result.all():
            parts = [str(first or "").strip(), str(last or "").strip()]
            name = " ".join(p for p in parts if p)
            user_names[int(uid)] = name or f"User #{uid}"

    engagement_names: dict[int, str] = {}
    if engagement_ids:
        result = await db.execute(
            select(Engagement.engagement_id, Engagement.engagement_name).where(
                Engagement.engagement_id.in_(engagement_ids)
            )
        )
        for eid, ename in result.all():
            text = (ename or "").strip()
            engagement_names[int(eid)] = text or f"#{eid}"

    return [_serviceability_row(log, user_names, engagement_names) for log in logs]


async def build_operations_snapshot(
    db: AsyncSession,
    *,
    employee: EmployeeContext,
) -> dict[str, Any]:
    from modules.payments.routes import get_payments_service
    from modules.support.router import get_support_service

    engagements_service = get_engagements_service()
    organizations_service = get_organizations_service()
    payments_service = get_payments_service()
    notifications_service = get_notifications_service()
    support_service = get_support_service()
    audit_service = get_audit_service()

    today = date.today()
    week_start, week_end = _week_range_local()

    async def load_engagements_block() -> dict:
        today_rows, today_trunc = await _engagement_rows_for_list(
            db, employee=employee, engagements_service=engagements_service, on_date=today
        )
        active_rows, active_trunc = await _engagement_rows_for_list(
            db, employee=employee, engagements_service=engagements_service, on_date=None
        )
        org_names = await _org_names_map(db, employee=employee, organizations_service=organizations_service)
        running_today = _keep_active(today_rows)
        running_this_week = [
            row
            for row in _keep_active(active_rows)
            if _ranges_overlap(row.get("start_date"), row.get("end_date"), week_start, week_end)
        ]
        return {
            "running_today": running_today,
            "running_this_week": running_this_week,
            "org_names": org_names,
            "truncated": today_trunc or active_trunc,
        }

    async def load_participant_issues() -> list[dict]:
        data = await engagements_service.list_engagements_data_completeness_summary(
            db,
            employee=employee,
            organization_id=None,
            camp_no=None,
            status="running,scheduled",
            city=None,
            on_date=None,
            search=None,
            engagement_type=None,
            audience=None,
            sort_by=None,
            sort_dir=None,
            limit=100,
            include_participant_issues=True,
        )
        return list(data.get("participant_issues") or [])

    async def load_pending_payments() -> list[dict]:
        payload = await payments_service.list_bookings_admin(
            db,
            page=1,
            limit=PAGE_SIZE,
            search=None,
            status="pending",
            sort_key="booking_id",
            sort_dir="desc",
        )
        items = payload.get("items") or []
        rows: list[dict] = []
        for booking in items:
            minutes = _pending_minutes(booking.get("booked_at"))
            if minutes is None or minutes <= PENDING_PAYMENT_THRESHOLD_MINUTES:
                continue
            rows.append({**booking, "pending_minutes": minutes})
        return rows

    async def load_failed_notifications() -> list[dict]:
        items, _total = await notifications_service.list_notifications(
            db,
            page=1,
            limit=PAGE_SIZE,
            status="failed",
        )
        return items

    async def load_tickets() -> dict:
        open_tickets = await support_service.list_tickets(db, status_filter="open")
        return {
            "open": [
                {
                    "ticket_id": t.ticket_id,
                    "user_id": t.user_id,
                    "contact_input": t.contact_input,
                    "query_text": t.query_text,
                    "status": t.status,
                    "created_at": t.created_at,
                }
                for t in open_tickets
            ],
        }

    async def load_serviceability() -> list[dict]:
        logs, _total = await audit_service.list_integration_sync_logs(
            db,
            page=1,
            limit=PAGE_SIZE,
            provider="healthians",
            statuses=["failed"],
            search="checkServiceabilityByLocation",
            payload_search=None,
        )
        return await _hydrate_serviceability_labels(db, logs)

    (
        engagements_block,
        participant_issues,
        pending_payments,
        failed_notifications,
        tickets_block,
        serviceability,
    ) = await asyncio.gather(
        load_engagements_block(),
        load_participant_issues(),
        load_pending_payments(),
        load_failed_notifications(),
        load_tickets(),
        load_serviceability(),
    )

    return {
        "engagements": engagements_block,
        "participant_issues": participant_issues,
        "pending_payments": pending_payments,
        "failed_notifications": failed_notifications,
        "tickets": tickets_block,
        "serviceability_issues": serviceability,
    }
