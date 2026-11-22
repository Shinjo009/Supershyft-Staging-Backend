"""Matching-role discovery for admin staff login (not authentication)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from common.phone import phone_lookup_candidates
from core.exceptions import AppError
from modules.employee.repository import EmployeeRepository
from modules.partners.repository import PartnersRepository
from modules.partners.role_utils import partner_role_value

_PARTNER_LABELS = {
    "phlebo": "Phlebo",
    "expert": "Expert",
    "organization_manager": "Organization Manager",
    "author": "Author",
}


@dataclass(frozen=True)
class EligibleRole:
    kind: str
    role: str
    label: str


class StaffAuthService:
    def __init__(
        self,
        *,
        employee_repository: EmployeeRepository | None = None,
        partners_repository: PartnersRepository | None = None,
    ):
        self._employees = employee_repository or EmployeeRepository()
        self._partners = partners_repository or PartnersRepository()

    async def list_eligible_roles(self, db: AsyncSession, phone: str) -> list[EligibleRole]:
        candidates = phone_lookup_candidates(phone, strict=True)
        if not candidates:
            raise AppError(status_code=400, error_code="INVALID_INPUT", message="Invalid request")

        results: list[EligibleRole] = []
        seen: set[tuple[str, str]] = set()

        employees = await self._employees.list_active_by_phones(db, candidates)
        for emp in employees:
            key = ("employee", "employee")
            if key in seen:
                continue
            seen.add(key)
            results.append(EligibleRole(kind="employee", role="employee", label="Employee"))

        partners = await self._partners.list_active_by_phones(db, candidates)
        # Stable order for UI
        order = ("phlebo", "expert", "organization_manager", "author")
        by_role: dict[str, EligibleRole] = {}
        for partner in partners:
            role = partner_role_value(partner.role)
            if role not in _PARTNER_LABELS:
                continue
            by_role[role] = EligibleRole(
                kind="partner",
                role=role,
                label=_PARTNER_LABELS[role],
            )
        for role in order:
            if role in by_role:
                key = ("partner", role)
                if key not in seen:
                    seen.add(key)
                    results.append(by_role[role])

        return results
