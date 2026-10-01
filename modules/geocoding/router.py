"""Geocoding HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from common.responses import success_response
from common.validation import ValidationError, sanitize_search_query
from core.exceptions import AppError
from db.session import get_db
from modules.employee.dependencies import get_current_employee
from modules.employee.service import EmployeeContext
from modules.geocoding.client import search_places_with_fallback
from modules.platform_settings.dependencies import get_platform_settings_service
from modules.platform_settings.service import PlatformSettingsService

router = APIRouter(prefix="/geocode", tags=["geocode"])


@router.get("/search")
async def geocode_search(
    q: str = Query(default="", min_length=0, max_length=500),
    limit: int = Query(default=3, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
    platform_settings_service: PlatformSettingsService = Depends(get_platform_settings_service),
):
    _ = employee
    try:
        query = sanitize_search_query(q, max_len=500)
    except ValidationError as exc:
        raise AppError(
            status_code=400,
            error_code="INVALID_INPUT",
            message=str(exc),
        ) from exc
    if len(query) < 3:
        raise AppError(
            status_code=400,
            error_code="INVALID_INPUT",
            message="Query must be at least 3 characters",
        )

    primary = await platform_settings_service.resolve_geocoding_provider(db)
    results, meta = await search_places_with_fallback(query, limit=limit, primary=primary)
    return success_response(results, meta=meta)
