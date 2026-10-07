"""Export log service.

Insert failure must fail the request.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.export_logs.models import ExportLog
from modules.export_logs.repository import ExportLogsRepository
from modules.export_logs.schemas import ExportLogCreateRequest


def _role_value(role: object) -> str:
    if role is None:
        return ""
    value = getattr(role, "value", None)
    if isinstance(value, str):
        return value
    return str(role)


class ExportLogsService:
    def __init__(self, repository: ExportLogsRepository):
        self._repository = repository

    async def create_log(
        self,
        db: AsyncSession,
        *,
        payload: ExportLogCreateRequest,
        employee_id: int,
    ) -> ExportLog:
        log = ExportLog(
            employee_id=employee_id,
            reason=payload.reason,
            export_type=payload.export_type,
            details=payload.details,
        )
        return await self._repository.create(db, log)

    async def create_contact_reveal(
        self,
        db: AsyncSession,
        *,
        employee_id: int,
        user_id: int,
        reason: str,
    ) -> ExportLog:
        log = ExportLog(
            employee_id=employee_id,
            reason=reason,
            export_type="contact_reveal",
            details={
                "export_format": None,
                "exported_participants": [user_id],
                "source_kind": "user",
                "source_id": str(user_id),
            },
        )
        return await self._repository.create(db, log)

    async def list_logs(
        self,
        db: AsyncSession,
        *,
        page: int,
        limit: int,
        search: str | None = None,
        employee_id: int | None = None,
        export_type: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = await self._repository.list_logs(
            db,
            page=page,
            limit=limit,
            search=search,
            employee_id=employee_id,
            export_type=export_type,
            created_from=created_from,
            created_to=created_to,
        )
        total = await self._repository.count_logs(
            db,
            search=search,
            employee_id=employee_id,
            export_type=export_type,
            created_from=created_from,
            created_to=created_to,
        )
        return [self._serialize(row, name, role) for row, name, role in rows], total

    @staticmethod
    def _serialize(row: ExportLog, employee_name: str, employee_role: object) -> dict[str, Any]:
        return {
            "export_log_id": row.export_log_id,
            "employee_id": row.employee_id,
            "employee_name": (employee_name or "").strip() or f"Employee {row.employee_id}",
            "employee_role": _role_value(employee_role),
            "reason": row.reason,
            "export_type": row.export_type,
            "details": row.details,
            "created_at": row.created_at,
        }
