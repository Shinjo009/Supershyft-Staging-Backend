"""Server health module dependencies."""

from __future__ import annotations

import secrets

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import settings
from core.exceptions import AppError
from modules.notifications.dependencies import get_notifications_service
from modules.notifications.service import NotificationsService
from modules.server_health.repository import ServerHealthRepository
from modules.server_health.service import ServerHealthService

_optional_http_bearer = HTTPBearer(auto_error=False)


def get_server_health_service() -> ServerHealthService:
    return ServerHealthService(ServerHealthRepository())


def get_server_health_notifications_service() -> NotificationsService:
    return get_notifications_service()


async def require_health_api_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_http_bearer),
) -> None:
    expected = (settings.HEALTH_API_TOKEN or "").strip()
    provided = (credentials.credentials if credentials is not None else "") or ""
    if not expected or not provided or not secrets.compare_digest(provided, expected):
        raise AppError(
            status_code=401,
            error_code="AUTH_FAILED",
            message="Authentication required: provide a valid health API bearer token",
        )
