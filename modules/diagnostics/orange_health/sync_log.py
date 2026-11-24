"""Integration sync logging for Orange Health API calls."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from db.session import AsyncSessionLocal
from modules.audit.models import IntegrationSyncLog
from modules.audit.repository import AuditRepository
from modules.diagnostics.orange_health.sync_log_payload import normalize_orange_health_request_payload


async def log_orange_health_call(
    db: AsyncSession,
    *,
    engagement_id: int | None,
    user_id: int | None,
    api_url: str,
    request_payload: dict | None,
    response_payload: dict | None = None,
    status: str,
    error_message: str | None = None,
    query_params: dict | None = None,
) -> IntegrationSyncLog:
    logged_request = normalize_orange_health_request_payload(
        api_url, request_payload, query=query_params
    )
    audit_repo = AuditRepository()
    return await audit_repo.create_sync_log(
        db,
        IntegrationSyncLog(
            engagement_id=engagement_id,
            user_id=user_id,
            provider="orange_health",
            api_endpoint_url=api_url,
            request_payload=logged_request,
            response_payload=response_payload,
            status=status,
            error_message=error_message,
        ),
    )


async def persist_orange_health_sync_log_isolated(
    *,
    engagement_id: int | None,
    user_id: int | None,
    api_url: str,
    request_payload: dict | None,
    response_payload: dict | None = None,
    status: str,
    error_message: str | None = None,
    query_params: dict | None = None,
) -> int:
    logged_request = normalize_orange_health_request_payload(
        api_url, request_payload, query=query_params
    )
    audit_repo = AuditRepository()
    async with AsyncSessionLocal() as audit_db:
        sync_log = await audit_repo.create_sync_log(
            audit_db,
            IntegrationSyncLog(
                engagement_id=engagement_id,
                user_id=user_id,
                provider="orange_health",
                api_endpoint_url=api_url,
                request_payload=logged_request,
                response_payload=response_payload,
                status=status,
                error_message=error_message,
            ),
        )
        await audit_db.commit()
        return int(sync_log.sync_log_id)


async def finalize_orange_health_sync_log_isolated(
    *,
    sync_log_id: int,
    status: str,
    response_payload: dict | None = None,
    error_message: str | None = None,
) -> None:
    audit_repo = AuditRepository()
    async with AsyncSessionLocal() as audit_db:
        await audit_repo.update_sync_log_status(
            audit_db,
            sync_log_id=sync_log_id,
            status=status,
            response_payload=response_payload,
            error_message=error_message,
        )
        await audit_db.commit()
