"""Export log database operations."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.validation import sanitize_search_query
from modules.employee.models import Employee
from modules.export_logs.models import ExportLog


class ExportLogsRepository:
    async def create(self, db: AsyncSession, log: ExportLog) -> ExportLog:
        db.add(log)
        await db.flush()
        return log

    def _apply_filters(
        self,
        query,
        *,
        search: str | None = None,
        employee_id: int | None = None,
        export_type: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ):
        if search:
            like = f"%{search}%"
            source_id = ExportLog.details["source_id"].astext
            source_name = ExportLog.details["source_name"].astext
            organization_name = ExportLog.details["organization_name"].astext
            engagement_name = ExportLog.details["engagement_name"].astext
            camp_name = ExportLog.details["camp_name"].astext
            query = query.where(
                or_(
                    Employee.name.ilike(like),
                    ExportLog.reason.ilike(like),
                    source_id.ilike(like),
                    source_name.ilike(like),
                    organization_name.ilike(like),
                    engagement_name.ilike(like),
                    camp_name.ilike(like),
                )
            )
        if employee_id is not None:
            query = query.where(ExportLog.employee_id == employee_id)
        if export_type:
            query = query.where(ExportLog.export_type == export_type)
        if created_from is not None:
            query = query.where(ExportLog.created_at >= created_from)
        if created_to is not None:
            query = query.where(ExportLog.created_at <= created_to)
        return query

    def _base_select(self):
        return (
            select(ExportLog, Employee.name, Employee.role)
            .join(Employee, Employee.employee_id == ExportLog.employee_id)
            .order_by(ExportLog.created_at.desc(), ExportLog.export_log_id.desc())
        )

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
    ) -> list[tuple[ExportLog, str, object]]:
        offset = (page - 1) * limit
        query = self._base_select()
        query = self._apply_filters(
            query,
            search=sanitize_search_query(search) or None,
            employee_id=employee_id,
            export_type=export_type,
            created_from=created_from,
            created_to=created_to,
        )
        result = await db.execute(query.offset(offset).limit(limit))
        return list(result.all())

    async def count_logs(
        self,
        db: AsyncSession,
        *,
        search: str | None = None,
        employee_id: int | None = None,
        export_type: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> int:
        query = (
            select(func.count())
            .select_from(ExportLog)
            .join(Employee, Employee.employee_id == ExportLog.employee_id)
        )
        query = self._apply_filters(
            query,
            search=sanitize_search_query(search) or None,
            employee_id=employee_id,
            export_type=export_type,
            created_from=created_from,
            created_to=created_to,
        )
        result = await db.execute(query)
        return int(result.scalar_one())
