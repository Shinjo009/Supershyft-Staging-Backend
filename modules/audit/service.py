"""Audit logging service.

Audit failure must fail the request.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.audit.models import DataAuditLog, IntegrationSyncLog
from modules.audit.payload_search import PayloadSearchCriteria
from modules.audit.repository import AuditRepository


class AuditService:
    """Service for creating audit logs."""

    def __init__(self, repository: AuditRepository):
        self._repository = repository

    async def log_event(
        self,
        db: AsyncSession,
        *,
        action: str,
        endpoint: str,
        ip_address: str,
        user_agent: str,
        user_id: Optional[int] = None,
        session_id: Optional[int] = None,
    ) -> None:
        log = DataAuditLog(
            user_id=user_id,
            session_id=session_id,
            action=action,
            ip_address=ip_address,
            user_agent=user_agent,
            endpoint=endpoint,
            timestamp=datetime.now(timezone.utc),
        )
        await self._repository.create_log(db, log)

    async def list_integration_sync_logs(
        self,
        db: AsyncSession,
        *,
        page: int,
        limit: int,
        provider: str | None = None,
        statuses: list[str] | None = None,
        user_id: int | None = None,
        engagement_id: int | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        search: str | None = None,
        payload_search: PayloadSearchCriteria | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = await self._repository.list_sync_logs(
            db,
            page=page,
            limit=limit,
            provider=provider,
            statuses=statuses,
            user_id=user_id,
            engagement_id=engagement_id,
            created_from=created_from,
            created_to=created_to,
            search=search,
            payload_search=payload_search,
        )
        total = await self._repository.count_sync_logs(
            db,
            provider=provider,
            statuses=statuses,
            user_id=user_id,
            engagement_id=engagement_id,
            created_from=created_from,
            created_to=created_to,
            search=search,
            payload_search=payload_search,
        )
        serialized = [self._serialize_sync_log(row) for row in rows]
        await self._embed_sync_log_display_names(db, serialized)
        return serialized, total

    async def _embed_sync_log_display_names(
        self, db: AsyncSession, items: list[dict[str, Any]]
    ) -> None:
        from modules.engagements.models import Engagement
        from modules.users.models import User

        user_ids = {int(item["user_id"]) for item in items if item.get("user_id") is not None}
        engagement_ids = {
            int(item["engagement_id"]) for item in items if item.get("engagement_id") is not None
        }
        user_names: dict[int, str] = {}
        if user_ids:
            result = await db.execute(
                select(User.user_id, User.first_name, User.last_name).where(User.user_id.in_(user_ids))
            )
            for uid, first, last in result.all():
                parts = [str(first or "").strip(), str(last or "").strip()]
                name = " ".join(p for p in parts if p)
                user_names[int(uid)] = name or f"User #{uid}"
        engagement_names: dict[int, str] = {}
        if engagement_ids:
            result = await db.execute(
                select(Engagement.engagement_id, Engagement.engagement_name).where(
                    Engagement.engagement_id.in_(engagement_ids)
                )
            )
            for eid, ename in result.all():
                text = (ename or "").strip()
                engagement_names[int(eid)] = text or f"#{eid}"

        for item in items:
            uid = item.get("user_id")
            if uid is not None:
                item["user_display_name"] = user_names.get(int(uid))
            eid = item.get("engagement_id")
            if eid is not None:
                item["engagement_display_name"] = engagement_names.get(int(eid))

    async def list_create_booking_dates_for_engagement(
        self,
        db: AsyncSession,
        *,
        engagement_id: int,
    ) -> dict[str, Any]:
        pairs = await self._repository.list_create_booking_dates_for_engagement(
            db,
            engagement_id=engagement_id,
        )
        user_ids_by_date: dict[str, list[int]] = {}
        for booking_date, user_id in pairs:
            date_key = booking_date.isoformat()
            bucket = user_ids_by_date.setdefault(date_key, [])
            if user_id not in bucket:
                bucket.append(user_id)
        dates = sorted(user_ids_by_date.keys(), reverse=True)
        return {"dates": dates, "user_ids_by_date": user_ids_by_date}

    @staticmethod
    def _serialize_sync_log(row: IntegrationSyncLog) -> dict[str, Any]:
        return {
            "sync_log_id": row.sync_log_id,
            "engagement_id": row.engagement_id,
            "user_id": row.user_id,
            "provider": row.provider,
            "api_endpoint_url": row.api_endpoint_url,
            "request_payload": row.request_payload,
            "response_payload": row.response_payload,
            "status": row.status,
            "error_message": row.error_message,
            "created_at": row.created_at,
        }
