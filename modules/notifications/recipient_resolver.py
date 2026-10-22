"""Resolve notification recipients by recipient_type for the event engine."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.employee.models import Employee, EmployeeRole
from modules.engagements.repository import EngagementsRepository
from modules.partners.models import Partner
from modules.platform_settings.repository import PlatformSettingsRepository
from modules.users.models import User

logger = logging.getLogger(__name__)


def _user_ids_from_payload(payload: dict[str, Any]) -> list[int]:
    ids: list[int] = []
    if isinstance(payload.get("user_id"), int):
        ids.append(int(payload["user_id"]))
    for uid in payload.get("user_ids") or []:
        if isinstance(uid, int):
            ids.append(uid)
    seen: set[int] = set()
    ordered: list[int] = []
    for uid in ids:
        if uid not in seen:
            seen.add(uid)
            ordered.append(uid)
    return ordered


async def _users_as_participant_contacts(
    db: AsyncSession, user_ids: list[int]
) -> list[dict[str, Any]]:
    if not user_ids:
        return []
    result = await db.execute(select(User).where(User.user_id.in_(user_ids)))
    contacts: list[dict[str, Any]] = []
    for user in result.scalars().all():
        contacts.append(
            {
                "user_id": user.user_id,
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "phone": user.phone or "",
                "email": user.email or "",
            }
        )
    return contacts


async def resolve_recipients(
    db: AsyncSession,
    *,
    recipient_type: str,
    payload: dict[str, Any],
    engagement_id: int | None,
) -> list[dict[str, Any]]:
    """Return contact dicts for dispatch_to_contacts or user_id lists for dispatch."""
    if recipient_type == "participant":
        members = payload.get("members")
        if isinstance(members, list) and members:
            contacts: list[dict[str, Any]] = []
            for item in members:
                if not isinstance(item, dict):
                    continue
                contacts.append(
                    {
                        "first_name": str(item.get("first_name") or ""),
                        "last_name": str(item.get("last_name") or ""),
                        "phone": str(item.get("phone") or ""),
                        "email": str(item.get("email") or ""),
                        "user_id": item.get("user_id"),
                    }
                )
            if contacts:
                return contacts
        user_ids = _user_ids_from_payload(payload)
        return await _users_as_participant_contacts(db, user_ids)

    if recipient_type == "onboarding_assistant":
        if engagement_id is None:
            platform_repo = PlatformSettingsRepository()
            return await _default_assistant_contacts(db, platform_repo=platform_repo)
        repo = EngagementsRepository()
        contacts = await repo.list_onboarding_assistant_notify_contacts(
            db, engagement_id=engagement_id, include_employees=True
        )
        return contacts or []

    if recipient_type == "partner" or recipient_type == "partner_role":
        partner_id = payload.get("partner_id")
        if isinstance(partner_id, int):
            result = await db.execute(
                select(Partner).where(Partner.partner_id == partner_id)
            )
            partner = result.scalar_one_or_none()
            if partner is not None:
                return [_partner_contact(partner)]
        role_hint = payload.get("partner_role")
        if engagement_id is not None and role_hint:
            return await _partners_by_role_on_engagement(
                db, engagement_id=engagement_id, role=str(role_hint)
            )
        return []

    if recipient_type == "admin":
        return await _admin_contacts(db)

    if recipient_type == "inferior_admin":
        return await _inferior_admin_contacts(db)

    logger.warning("Unknown recipient_type=%s", recipient_type)
    return []


def _partner_contact(partner: Partner) -> dict[str, Any]:
    name = (partner.name or "").strip()
    parts = name.split(None, 1)
    return {
        "partner_id": int(partner.partner_id),
        "name": name,
        "first_name": parts[0] if parts else "",
        "last_name": parts[1] if len(parts) > 1 else "",
        "phone": partner.phone or "",
        "email": partner.email or "",
        "role": partner.role,
    }


async def _partners_by_role_on_engagement(
    db: AsyncSession, *, engagement_id: int, role: str
) -> list[dict[str, Any]]:
    repo = EngagementsRepository()
    contacts = await repo.list_onboarding_assistant_notify_contacts(
        db, engagement_id=engagement_id, include_employees=False
    )
    role_norm = role.strip().lower()
    filtered: list[dict[str, Any]] = []
    for c in contacts:
        if str(c.get("role") or "").lower() == role_norm:
            filtered.append(c)
    return filtered


async def _default_assistant_contacts(
    db: AsyncSession, *, platform_repo: PlatformSettingsRepository
) -> list[dict[str, Any]]:
    partner_ids = await platform_repo.resolve_default_onboarding_assistant_employee_ids(db)
    if not partner_ids:
        return []
    result = await db.execute(
        select(Partner)
        .where(Partner.partner_id.in_(partner_ids))
        .where(Partner.status == "active")
    )
    return [_partner_contact(p) for p in result.scalars().all()]


async def _admin_contacts(db: AsyncSession) -> list[dict[str, Any]]:
    result = await db.execute(
        select(Employee)
        .where(Employee.role == EmployeeRole.admin)
        .where(Employee.status == "active")
    )
    contacts: list[dict[str, Any]] = []
    for emp in result.scalars().all():
        contacts.append(
            {
                "employee_id": emp.employee_id,
                "first_name": emp.name or "",
                "last_name": "",
                "phone": emp.phone or "",
                "email": emp.email or "",
            }
        )
    return contacts


async def _inferior_admin_contacts(db: AsyncSession) -> list[dict[str, Any]]:
    result = await db.execute(
        select(Employee)
        .where(Employee.role == EmployeeRole.inferior_admin)
        .where(Employee.status == "active")
    )
    contacts: list[dict[str, Any]] = []
    for emp in result.scalars().all():
        contacts.append(
            {
                "employee_id": emp.employee_id,
                "first_name": emp.name or "",
                "last_name": "",
                "phone": emp.phone or "",
                "email": emp.email or "",
            }
        )
    return contacts


def recipient_uses_user_dispatch(contacts: list[dict[str, Any]]) -> list[int] | None:
    """If all contacts have user_id and no partner/employee-only fields, return user_ids."""
    if not contacts:
        return None
    user_ids: list[int] = []
    for c in contacts:
        uid = c.get("user_id")
        if isinstance(uid, int):
            user_ids.append(uid)
        elif "partner_id" in c or "employee_id" in c:
            return None
        else:
            return None
    return user_ids if user_ids else None
