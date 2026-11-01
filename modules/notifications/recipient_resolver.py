"""Resolve notification recipients by recipient_type."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.employee.access_control import ONBOARDING_ASSISTANT_ASSIGNEE_EMPLOYEE_ROLES
from modules.employee.models import Employee, EmployeeRole
from modules.engagements.repository import EngagementsRepository
from modules.experts.repository import ExpertsRepository
from modules.notifications.binding_resolver import ResolvedBinding
from modules.notifications.consultation_booking_alert_notify import (
    resolve_consultation_booking_alert_contacts,
)
from modules.notifications.support_notify import _resolve_default_assistant_contacts
from modules.platform_settings.repository import PlatformSettingsRepository
from modules.users.models import User


@dataclass
class ResolvedRecipients:
    user_ids: list[int] = field(default_factory=list)
    contacts: list[dict] = field(default_factory=list)
    members_for_individual_dispatch: list[dict] = field(default_factory=list)


async def resolve_recipients(
    db: AsyncSession,
    *,
    recipient_type: str,
    payload: dict[str, Any],
    binding: ResolvedBinding,
    engagement_id: int | None,
) -> ResolvedRecipients:
    rt = recipient_type.strip().lower()
    if rt == "participant":
        return await _resolve_participant(db, payload)
    if rt == "booker":
        return await _resolve_booker(db, payload)
    if rt == "family_member":
        return _resolve_family_members(payload)
    if rt == "partner":
        contacts = payload.get("contacts")
        if isinstance(contacts, list) and contacts:
            return ResolvedRecipients(contacts=[c for c in contacts if isinstance(c, dict)])
        return _resolve_partner(payload)
    if rt == "employee":
        return _resolve_employee(payload)
    if rt == "admin":
        return await _resolve_admin(db, payload)
    if rt == "custom":
        return _resolve_custom(binding, payload)
    if rt.startswith("oa."):
        return await _resolve_oa(db, rt, payload, engagement_id)
    return ResolvedRecipients()


async def _resolve_participant(db: AsyncSession, payload: dict[str, Any]) -> ResolvedRecipients:
    user_id = payload.get("user_id")
    if isinstance(user_id, int):
        return ResolvedRecipients(user_ids=[user_id])
    user = payload.get("user")
    if isinstance(user, dict) and isinstance(user.get("user_id"), int):
        return ResolvedRecipients(user_ids=[int(user["user_id"])])
    if isinstance(user, dict) and (user.get("phone") or user.get("email")):
        return ResolvedRecipients(
            contacts=[
                {
                    "first_name": user.get("first_name") or "",
                    "last_name": user.get("last_name") or "",
                    "phone": user.get("phone") or "",
                    "email": user.get("email") or "",
                }
            ]
        )
    return ResolvedRecipients()


async def _resolve_booker(db: AsyncSession, payload: dict[str, Any]) -> ResolvedRecipients:
    booker_id = payload.get("booker_user_id") or payload.get("booker_id")
    if isinstance(booker_id, int):
        return ResolvedRecipients(user_ids=[booker_id])
    booker = payload.get("booker")
    if isinstance(booker, dict) and isinstance(booker.get("user_id"), int):
        return ResolvedRecipients(user_ids=[int(booker["user_id"])])
    return ResolvedRecipients()


def _resolve_family_members(payload: dict[str, Any]) -> ResolvedRecipients:
    members = payload.get("members")
    if not isinstance(members, list):
        return ResolvedRecipients()
    out: list[dict] = []
    user_ids: list[int] = []
    for member in members:
        if not isinstance(member, dict):
            continue
        uid = member.get("user_id")
        if isinstance(uid, int):
            user_ids.append(uid)
            continue
        out.append(
            {
                "first_name": str(member.get("first_name") or ""),
                "last_name": str(member.get("last_name") or ""),
                "phone": str(member.get("phone") or ""),
                "email": str(member.get("email") or ""),
            }
        )
    if user_ids and not out:
        return ResolvedRecipients(members_for_individual_dispatch=[{"user_id": uid} for uid in user_ids])
    return ResolvedRecipients(members_for_individual_dispatch=out or [{"user_id": uid} for uid in user_ids])


def _resolve_partner(payload: dict[str, Any]) -> ResolvedRecipients:
    partner = payload.get("partner")
    if isinstance(partner, dict):
        return ResolvedRecipients(
            contacts=[
                {
                    "partner_id": partner.get("partner_id"),
                    "first_name": partner.get("first_name") or "",
                    "last_name": partner.get("last_name") or "",
                    "phone": partner.get("phone") or "",
                    "email": partner.get("email") or "",
                    "name": partner.get("name") or "",
                }
            ]
        )
    contacts = payload.get("contacts")
    if isinstance(contacts, list):
        return ResolvedRecipients(contacts=[c for c in contacts if isinstance(c, dict)])
    return ResolvedRecipients()


def _resolve_employee(payload: dict[str, Any]) -> ResolvedRecipients:
    employee = payload.get("employee")
    if isinstance(employee, dict):
        name = str(employee.get("name") or "").strip()
        parts = name.split(None, 1)
        return ResolvedRecipients(
            contacts=[
                {
                    "employee_id": employee.get("employee_id"),
                    "first_name": employee.get("first_name") or (parts[0] if parts else ""),
                    "last_name": employee.get("last_name") or (parts[1] if len(parts) > 1 else ""),
                    "phone": employee.get("phone") or "",
                    "email": employee.get("email") or "",
                    "name": name,
                }
            ]
        )
    return ResolvedRecipients(contacts=payload.get("contacts") if isinstance(payload.get("contacts"), list) else [])


async def _resolve_admin(db: AsyncSession, payload: dict[str, Any]) -> ResolvedRecipients:
    user_ids_raw = payload.get("user_ids")
    if isinstance(user_ids_raw, list):
        uids = [int(u) for u in user_ids_raw if isinstance(u, int)]
        if uids:
            return ResolvedRecipients(user_ids=uids)
    platform_repo = PlatformSettingsRepository()
    contacts = await _resolve_default_assistant_contacts(
        db, platform_settings_repository=platform_repo
    )
    if contacts:
        return ResolvedRecipients(contacts=contacts)
    result = await db.execute(
        select(Employee).where(Employee.status == "active").where(Employee.role == EmployeeRole.admin)
    )
    out: list[dict] = []
    for emp in result.scalars().all():
        name = (emp.name or "").strip()
        parts = name.split(None, 1)
        out.append(
            {
                "employee_id": emp.employee_id,
                "first_name": parts[0] if parts else "",
                "last_name": parts[1] if len(parts) > 1 else "",
                "phone": emp.phone or "",
                "email": emp.email or "",
            }
        )
    return ResolvedRecipients(contacts=out)


def _resolve_custom(binding: ResolvedBinding, payload: dict[str, Any]) -> ResolvedRecipients:
    custom = binding.custom_contacts or {}
    if isinstance(payload.get("custom_contacts"), dict):
        custom = payload["custom_contacts"]
    phones = custom.get("phones") if isinstance(custom, dict) else []
    emails = custom.get("emails") if isinstance(custom, dict) else []
    contacts: list[dict] = []
    for phone in phones or []:
        contacts.append({"phone": str(phone), "first_name": "", "last_name": "", "email": ""})
    for email in emails or []:
        contacts.append({"email": str(email), "first_name": "", "last_name": "", "phone": ""})
    return ResolvedRecipients(contacts=contacts)


async def _resolve_oa(
    db: AsyncSession,
    recipient_type: str,
    payload: dict[str, Any],
    engagement_id: int | None,
) -> ResolvedRecipients:
    if engagement_id is None:
        return ResolvedRecipients()
    engagements_repo = EngagementsRepository()
    if recipient_type == "oa.phlebo":
        contacts = await engagements_repo.list_onboarding_assistant_partner_contacts(
            db, engagement_id=engagement_id, roles=frozenset({"phlebo"})
        )
        return ResolvedRecipients(contacts=contacts)
    if recipient_type == "oa.staff":
        contacts = await engagements_repo.list_onboarding_assistant_notify_contacts(
            db, engagement_id=engagement_id, include_employees=True
        )
        return ResolvedRecipients(contacts=contacts)
    if recipient_type == "oa.all":
        partners = await engagements_repo.list_onboarding_assistant_partner_contacts(
            db, engagement_id=engagement_id, roles=None
        )
        staff = await engagements_repo.list_onboarding_assistant_notify_contacts(
            db, engagement_id=engagement_id, include_employees=True
        )
        return ResolvedRecipients(contacts=[*partners, *staff])
    if recipient_type == "oa.expert":
        engagement = payload.get("engagement")
        if engagement is None:
            return ResolvedRecipients()
        contacts = await resolve_consultation_booking_alert_contacts(
            db,
            engagement=engagement,
            expert_type=str(payload.get("expert_type") or ""),
            expert_id=payload.get("expert_id"),
            engagements_repository=engagements_repo,
            experts_repository=ExpertsRepository(),
        )
        return ResolvedRecipients(contacts=contacts)
    return ResolvedRecipients()


async def load_user_if_needed(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.user_id == user_id))
    return result.scalar_one_or_none()
