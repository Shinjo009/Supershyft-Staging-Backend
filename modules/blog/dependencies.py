"""Author and admin access for the blog dashboard."""

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
from modules.blog.author_link import ensure_author_profile, ensure_employee_author
from modules.blog.models import Author
from modules.employee.models import EmployeeRole
from modules.employee.permissions import PermissionAction, inferior_admin_task_allowed
from modules.partners.role_utils import partner_role_value

_bearer = HTTPBearer(auto_error=False)


@dataclass
class BlogActor:
    author: Author
    is_admin: bool = False


def _role_text(role) -> str:
    if isinstance(role, EmployeeRole):
        return role.value
    return str(role or "")


def _forbidden() -> AppError:
    return AppError(
        status_code=403,
        error_code="FORBIDDEN",
        message="You do not have permission to perform this action",
    )


async def _employee_blog_actor(
    db: AsyncSession,
    employee,
    *,
    task_key: str,
    action: PermissionAction,
) -> BlogActor | None:
    role = _role_text(employee.role)
    if role == EmployeeRole.admin.value:
        return BlogActor(author=await ensure_employee_author(db, employee), is_admin=True)
    if role != EmployeeRole.inferior_admin.value:
        return None
    if await inferior_admin_task_allowed(
        db, employee.employee_id, "blog", task_key, action
    ):
        return BlogActor(author=await ensure_employee_author(db, employee), is_admin=True)
    return None


async def _actor_from_credentials(
    db: AsyncSession,
    credentials: HTTPAuthorizationCredentials | None,
    *,
    required: bool,
    request: Request | None = None,
    optional_posts_view: bool = False,
) -> BlogActor | None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        if required:
            raise AppError(status_code=401, error_code="AUTH_FAILED", message="Authentication failed")
        return None

    try:
        payload = decode_and_verify_jwt(credentials.credentials)
        typ = jwt_subject_typ(payload)
    except Exception as exc:
        if required:
            raise AppError(status_code=401, error_code="AUTH_FAILED", message="Authentication failed") from exc
        return None

    if typ == "partner":
        partner = await get_current_partner_from_token(db, credentials)
        if partner_role_value(partner.role) != "author":
            if required:
                raise _forbidden()
            return None
        author = await ensure_author_profile(db, partner)
        if author is None:
            if required:
                raise _forbidden()
            return None
        return BlogActor(author=author, is_admin=False)

    if typ == "employee":
        employee = await get_current_employee_from_token(db, credentials)
        capability = getattr(request.state, "rbac_capability", None) if request else None
        if capability is not None and capability.category == "blog":
            actor = await _employee_blog_actor(
                db,
                employee,
                task_key=capability.task_key,
                action=capability.action,
            )
            if actor is not None:
                return actor
            if required:
                raise _forbidden()
            return None
        if optional_posts_view:
            actor = await _employee_blog_actor(
                db,
                employee,
                task_key="posts",
                action=PermissionAction.view,
            )
            if actor is not None:
                return actor
            return None
        actor = await _employee_blog_actor(
            db,
            employee,
            task_key="posts",
            action=PermissionAction.edit,
        )
        if actor is not None:
            return actor
        if _role_text(employee.role) == EmployeeRole.admin.value:
            return BlogActor(author=await ensure_employee_author(db, employee), is_admin=True)
        if required:
            raise _forbidden()
        return None

    if required:
        raise _forbidden()
    return None


async def get_current_author(
    request: Request,
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> BlogActor:
    actor = await _actor_from_credentials(db, credentials, required=True, request=request)
    assert actor is not None
    return actor


async def get_optional_author(
    request: Request,
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> BlogActor | None:
    """Return an actor when a valid author/admin token is present; otherwise None."""
    return await _actor_from_credentials(
        db,
        credentials,
        required=False,
        request=request,
        optional_posts_view=True,
    )
