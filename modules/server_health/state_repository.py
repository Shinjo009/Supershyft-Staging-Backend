"""Read/write Postgres host state for health_check.sh metrics and CPU alerts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.server_health.models import ServerHealthHostState


class ServerHealthStateRepository:
    async def get_locked_by_hostname(
        self, db: AsyncSession, *, hostname: str
    ) -> ServerHealthHostState | None:
        result = await db.execute(
            select(ServerHealthHostState)
            .where(ServerHealthHostState.hostname == hostname)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_latest(self, db: AsyncSession) -> ServerHealthHostState | None:
        result = await db.execute(
            select(ServerHealthHostState).order_by(ServerHealthHostState.reported_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    def create(
        self,
        *,
        hostname: str,
        cpu_usage: float,
        memory_usage: float,
        storage_usage: float,
        load_1m: float,
        cores: int,
        reported_at: datetime,
    ) -> ServerHealthHostState:
        return ServerHealthHostState(
            hostname=hostname,
            cpu_usage=cpu_usage,
            memory_usage=memory_usage,
            storage_usage=storage_usage,
            load_1m=load_1m,
            cores=cores,
            reported_at=reported_at,
            is_alerting=False,
        )
