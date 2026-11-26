"""Support repository.

Only database queries live here.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.listing import apply_sort
from modules.support.models import SupportTicket


class SupportRepository:
    """Support ticket database queries."""

    async def create_ticket(
        self,
        db: AsyncSession,
        data: dict,
        *,
        user_id: int | None = None,
    ) -> SupportTicket:
        ticket = SupportTicket(user_id=user_id, **data)
        db.add(ticket)
        await db.flush()
        return ticket

    async def count_tickets(
        self,
        db: AsyncSession,
        *,
        status: str | None = None,
    ) -> int:
        query = select(func.count()).select_from(SupportTicket)
        if status is not None:
            query = query.where(SupportTicket.status == status)
        result = await db.execute(query)
        return int(result.scalar_one() or 0)

    async def get_all_tickets(
        self,
        db: AsyncSession,
        *,
        status: str | None = None,
        page: int = 1,
        limit: int = 20,
        sort_by: str | None = None,
        sort_dir: str | None = None,
    ) -> list[SupportTicket]:
        offset = (page - 1) * limit
        query = select(SupportTicket)
        if status is not None:
            query = query.where(SupportTicket.status == status)
        query = apply_sort(
            query,
            sort_by=sort_by,
            sort_dir=sort_dir,
            columns={
                "ticket_id": SupportTicket.ticket_id,
                "created_at": SupportTicket.created_at,
                "status": SupportTicket.status,
            },
            default_column=SupportTicket.ticket_id,
        )
        query = query.offset(offset).limit(limit)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_ticket_by_id(self, db: AsyncSession, ticket_id: int) -> SupportTicket | None:
        result = await db.execute(select(SupportTicket).where(SupportTicket.ticket_id == ticket_id))
        return result.scalar_one_or_none()

    async def update_ticket_status(
        self,
        db: AsyncSession,
        ticket_id: int,
        status: str,
        *,
        resolved_by_employee_id: int | None = None,
        resolved_at: datetime | None = None,
        resolution_notes: str | None = None,
        update_resolution_notes: bool = False,
        clear_resolution: bool = False,
    ) -> SupportTicket | None:
        ticket = await self.get_ticket_by_id(db, ticket_id)
        if ticket is None:
            return None

        ticket.status = status
        if clear_resolution:
            ticket.resolved_by_employee_id = None
            ticket.resolved_at = None
        else:
            if resolved_by_employee_id is not None:
                ticket.resolved_by_employee_id = resolved_by_employee_id
            if resolved_at is not None:
                ticket.resolved_at = resolved_at
        if update_resolution_notes:
            ticket.resolution_notes = resolution_notes

        db.add(ticket)
        await db.flush()
        return ticket
