"""Employee HTTP routes for user onboarding payload field catalog."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from common.responses import success_response
from core.exceptions import AppError
from db.session import get_db
from modules.employee.dependencies import get_current_employee
from modules.employee.service import EmployeeContext
from modules.engagements.dependencies import get_user_onboarding_payload_fields_service
from modules.engagements.onboarding_payload_schemas import (
    UserOnboardingPayloadFieldCreateRequest,
    UserOnboardingPayloadFieldUpdateRequest,
)
from modules.engagements.onboarding_payload_service import UserOnboardingPayloadFieldsService

router = APIRouter(prefix="/user-onboarding-payload-fields", tags=["engagements"])


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client is None:
        return "unknown"
    return request.client.host


@router.get("")
async def list_user_onboarding_payload_fields(
    page: int = 1,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
    service: UserOnboardingPayloadFieldsService = Depends(get_user_onboarding_payload_fields_service),
):
    if page < 1 or limit < 1 or limit > 100:
        raise AppError(status_code=400, error_code="INVALID_INPUT", message="Invalid request")

    rows, total = await service.list_fields(db, employee=employee, page=page, limit=limit)
    data = [UserOnboardingPayloadFieldsService.row_to_dict(row) for row in rows]
    return success_response(data, meta={"page": page, "limit": limit, "total": total})


@router.post("", status_code=201)
async def create_user_onboarding_payload_field(
    payload: UserOnboardingPayloadFieldCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
    service: UserOnboardingPayloadFieldsService = Depends(get_user_onboarding_payload_fields_service),
):
    row = await service.create_field(
        db,
        employee=employee,
        payload=payload,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("User-Agent", "unknown"),
        endpoint=str(request.url.path),
    )
    await db.commit()
    return success_response(UserOnboardingPayloadFieldsService.row_to_dict(row))


@router.put("/{field_id}")
async def update_user_onboarding_payload_field(
    field_id: int,
    payload: UserOnboardingPayloadFieldUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
    service: UserOnboardingPayloadFieldsService = Depends(get_user_onboarding_payload_fields_service),
):
    row = await service.update_field(
        db,
        employee=employee,
        field_id=field_id,
        payload=payload,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("User-Agent", "unknown"),
        endpoint=str(request.url.path),
    )
    await db.commit()
    return success_response(UserOnboardingPayloadFieldsService.row_to_dict(row))


@router.delete("/{field_id}")
async def delete_user_onboarding_payload_field(
    field_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
    service: UserOnboardingPayloadFieldsService = Depends(get_user_onboarding_payload_fields_service),
):
    await service.delete_field(
        db,
        employee=employee,
        field_id=field_id,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("User-Agent", "unknown"),
        endpoint=str(request.url.path),
    )
    await db.commit()
    return success_response({"deleted": True})
