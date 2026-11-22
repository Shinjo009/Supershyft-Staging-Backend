"""Staff matching-role discovery routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from common.responses import success_response
from core.rate_limit import limiter
from db.session import get_db
from modules.staff_auth.schemas import EligibleRolesRequest
from modules.staff_auth.service import StaffAuthService

router = APIRouter(prefix="/staff/auth", tags=["staff-auth"])


def get_staff_auth_service() -> StaffAuthService:
    return StaffAuthService()


@router.post("/eligible-roles")
@limiter.limit("10/minute")
async def eligible_roles(
    payload: EligibleRolesRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: StaffAuthService = Depends(get_staff_auth_service),
):
    roles = await service.list_eligible_roles(db, payload.phone)
    return success_response(
        {
            "roles": [
                {"kind": r.kind, "role": r.role, "label": r.label}
                for r in roles
            ]
        }
    )
