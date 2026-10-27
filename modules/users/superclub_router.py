"""Super Club admin routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from common.listing import sanitize_list_search
from common.masking import mask_email, mask_phone
from common.responses import success_response
from core.exceptions import AppError
from db.session import get_db
from modules.employee.dependencies import get_current_employee
from modules.employee.service import EmployeeContext
from modules.users.dependencies import get_users_service
from modules.users.superclub_catalog import normalize_sports_playlists
from modules.users.service import UsersService

router = APIRouter(prefix="/superclub", tags=["superclub"])


@router.get("/playlists")
async def list_superclub_playlists(
    page: int = 1,
    limit: int = 20,
    search: str | None = None,
    sport_id: list[str] | None = Query(default=None),
    other_selected: bool | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
    db: AsyncSession = Depends(get_db),
    employee: EmployeeContext = Depends(get_current_employee),
    users_service: UsersService = Depends(get_users_service),
):
    if page < 1 or limit < 1 or limit > 100:
        raise AppError(status_code=400, error_code="INVALID_INPUT", message="Invalid request")

    try:
        search = sanitize_list_search(search)
    except ValidationError as exc:
        raise AppError(status_code=400, error_code="INVALID_INPUT", message=str(exc)) from exc

    sport_ids = [item.strip() for item in (sport_id or []) if (item or "").strip()]

    rows, total, stats_meta = await users_service.list_superclub_playlists_for_employee(
        db,
        employee=employee,
        page=page,
        limit=limit,
        search=search,
        sport_ids=sport_ids or None,
        other_selected=other_selected,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )

    data = []
    for user, preference in rows:
        sports_playlists = normalize_sports_playlists(preference.sports_playlists)
        data.append(
            {
                "user_id": user.user_id,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "phone": mask_phone(user.phone),
                "email": mask_email(user.email),
                "city": user.city,
                "status": user.status,
                "is_participant": user.is_participant,
                "created_at": user.created_at,
                "sports_playlists": sports_playlists,
                "playlist_updated_at": preference.updated_at,
            }
        )

    return success_response(
        data,
        meta={
            "page": page,
            "limit": limit,
            "total": total,
            **stats_meta,
        },
    )
