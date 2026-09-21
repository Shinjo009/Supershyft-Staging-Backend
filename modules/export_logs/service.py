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


class ExportLogsService:
    def __init__(self, repository: ExportLogsRepository):
        self._repository = repository

    async def create_log(
        self,
        db: AsyncSession,
        *,
        payload: ExportLogCreateRequest,
        employee_id: int | None,
        partner_id: int | None,
        actor_name: str,
        actor_role: str,
        ip_address: str,
        user_agent: str,
    ) -> ExportLog:
        log = ExportLog(
            employee_id=employee_id,
            partner_id=partner_id,
            actor_name=actor_name,
            actor_role=actor_role,
            reason=payload.reason,
            export_type=payload.export_type,
            export_format=payload.export_format,
            source_kind=payload.source_kind,
            source_id=payload.source_id,
            row_count=payload.row_count,
            details=payload.details,
            ip_address=ip_address,
            user_agent=user_agent,
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
        return [self._serialize(row) for row in rows], total

    @staticmethod
    def _serialize(row: ExportLog) -> dict[str, Any]:
        return {
            "export_log_id": row.export_log_id,
            "employee_id": row.employee_id,
            "partner_id": row.partner_id,
            "actor_name": row.actor_name,
            "actor_role": row.actor_role,
            "reason": row.reason,
            "export_type": row.export_type,
            "export_format": row.export_format,
            "source_kind": row.source_kind,
            "source_id": row.source_id,
            "row_count": row.row_count,
            "details": row.details,
            "ip_address": row.ip_address,
            "user_agent": row.user_agent,
            "created_at": row.created_at,
        }
