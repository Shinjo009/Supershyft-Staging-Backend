"""Auth actor for diagnostic package mutations (employee admin or end user)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import authenticate_bearer_user, get_current_employee_from_token
from core.exceptions import AppError
from core.security import decode_and_verify_jwt
from core.subject_auth import jwt_subject_typ
from db.session import get_db
from modules.employee.dependencies import get_employee_service
from modules.employee.service import EmployeeContext, EmployeeService

_http_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class DiagnosticsPackageActor:
    """Caller for package create/update and test-group assignment."""

    employee: EmployeeContext | None
    current_user_id: int | None


async def get_diagnostics_package_actor(
    request: Request,
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_http_bearer),
    employee_service: EmployeeService = Depends(get_employee_service),
) -> DiagnosticsPackageActor:
    """Accept employee JWT (admin) or user JWT (custom package owner)."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(status_code=401, error_code="AUTH_FAILED", message="Authentication failed")

    try:
        payload = decode_and_verify_jwt(credentials.credentials)
        typ = jwt_subject_typ(payload)
    except Exception as exc:
        raise AppError(status_code=401, error_code="AUTH_FAILED", message="Authentication failed") from exc

    if typ == "employee":
        employee_row = await get_current_employee_from_token(db, credentials)
        employee = await employee_service.get_active_employee_by_id(
            db,
            employee_row.employee_id,
            capability=getattr(request.state, "rbac_capability", None),
        )
        return DiagnosticsPackageActor(employee=employee, current_user_id=None)

    if typ == "user":
        user = await authenticate_bearer_user(db, credentials)
        return DiagnosticsPackageActor(employee=None, current_user_id=user.user_id)

    raise AppError(status_code=401, error_code="AUTH_FAILED", message="Authentication failed")
