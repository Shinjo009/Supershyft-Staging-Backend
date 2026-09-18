"""Dependencies for export log routes."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import get_current_employee_from_token, get_current_partner_from_token
from core.exceptions import AppError
from core.security import decode_and_verify_jwt
from core.subject_auth import jwt_subject_typ
from db.session import get_db
from modules.employee.dependencies import get_employee_service
from modules.employee.service import EmployeeContext, EmployeeService
from modules.export_logs.repository import ExportLogsRepository
from modules.export_logs.service import ExportLogsService
from modules.partners.models import Partner

_http_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class ExportActor:
    employee: EmployeeContext | None = None
    partner: Partner | None = None
    actor_name: str = ""
    actor_role: str = ""
    employee_id: int | None = None
    partner_id: int | None = None


def get_export_logs_service() -> ExportLogsService:
    return ExportLogsService(ExportLogsRepository())


def _role_value(role: object) -> str:
    if role is None:
        return ""
    value = getattr(role, "value", None)
    if isinstance(value, str):
        return value
    return str(role)


async def get_export_actor(
    request: Request,
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_http_bearer),
    employee_service: EmployeeService = Depends(get_employee_service),
) -> ExportActor:
    """Accept an active employee or partner JWT."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(status_code=401, error_code="AUTH_FAILED", message="Authentication failed")

    try:
        payload = decode_and_verify_jwt(credentials.credentials)
        typ = jwt_subject_typ(payload)
    except Exception as exc:
        raise AppError(status_code=401, error_code="AUTH_FAILED", message="Authentication failed") from exc

    if typ == "partner":
        partner = await get_current_partner_from_token(db, credentials)
        return ExportActor(
            partner=partner,
            actor_name=(partner.name or "").strip() or f"Partner {partner.partner_id}",
            actor_role=_role_value(partner.role),
            partner_id=partner.partner_id,
        )

    if typ == "employee":
        employee_row = await get_current_employee_from_token(db, credentials)
        employee = await employee_service.get_active_employee_by_id(
            db,
            employee_row.employee_id,
            capability=getattr(request.state, "rbac_capability", None),
        )
        return ExportActor(
            employee=employee,
            actor_name=(employee_row.name or "").strip() or f"Employee {employee.employee_id}",
            actor_role=_role_value(employee.role),
            employee_id=employee.employee_id,
        )

    raise AppError(status_code=401, error_code="AUTH_FAILED", message="Authentication failed")
