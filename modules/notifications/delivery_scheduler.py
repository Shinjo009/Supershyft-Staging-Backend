"""Schedule notification delivery inline or via FastAPI BackgroundTasks."""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass
from collections.abc import AsyncGenerator
from typing import Any, Awaitable, Callable, TypeVar

from fastapi import BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Paths that must finish delivery before the HTTP response (cron HTTP triggers, n8n callback).
SYNC_DELIVERY_PATHS: frozenset[str] = frozenset(
    {
        "/notifications/callback",
        "/notifications/questionnaire-reminders/dispatch",
    }
)

_current_scheduler: ContextVar["DeliveryScheduler | None"] = ContextVar(
    "notification_delivery_scheduler",
    default=None,
)


def path_requires_sync_delivery(request: Request) -> bool:
    path = (request.url.path or "").rstrip("/") or "/"
    return path in SYNC_DELIVERY_PATHS


@dataclass(frozen=True, slots=True)
class PendingDeliverJob:
    notification_id: int
    service_key: str
    members: list[dict[str, Any]]
    engagement_id: int | None
    participant_details: dict[str, Any] | None
    sync_log_user_id: int | None


class DeliveryScheduler:
    """Runs notification delivery work inline or after the HTTP response."""

    @property
    def defer_enabled(self) -> bool:
        return False

    async def invoke(
        self,
        fn: Callable[[AsyncSession], Awaitable[T]],
        *,
        db: AsyncSession | None = None,
    ) -> T | None:
        if db is None:
            raise ValueError("db session required for synchronous notification delivery")
        return await fn(db)


class BackgroundDeliveryScheduler(DeliveryScheduler):
    def __init__(self, background_tasks: BackgroundTasks) -> None:
        self._background_tasks = background_tasks

    @property
    def defer_enabled(self) -> bool:
        return bool(settings.NOTIFICATION_DEFER_HTTP_DELIVERY)

    async def invoke(
        self,
        fn: Callable[[AsyncSession], Awaitable[T]],
        *,
        db: AsyncSession | None = None,
    ) -> T | None:
        if not self.defer_enabled:
            if db is None:
                raise ValueError("db session required for synchronous notification delivery")
            return await fn(db)
        self._background_tasks.add_task(_run_delivery_in_fresh_session, fn)
        return None


async def _run_delivery_in_fresh_session(
    fn: Callable[[AsyncSession], Awaitable[Any]],
) -> None:
    async with AsyncSessionLocal() as db:
        try:
            await fn(db)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Background notification delivery failed")


def get_delivery_scheduler() -> DeliveryScheduler:
    scheduler = _current_scheduler.get()
    if scheduler is not None:
        return scheduler
    return DeliveryScheduler()


def set_delivery_scheduler(scheduler: DeliveryScheduler) -> Token:
    return _current_scheduler.set(scheduler)


def reset_delivery_scheduler(token: Token) -> None:
    _current_scheduler.reset(token)


async def bind_notification_delivery_scheduler(
    request: Request,
    background_tasks: BackgroundTasks,
) -> AsyncGenerator[None, None]:
    """App dependency: defer delivery on HTTP except allowlisted sync paths."""
    if path_requires_sync_delivery(request):
        token = set_delivery_scheduler(DeliveryScheduler())
    else:
        token = set_delivery_scheduler(BackgroundDeliveryScheduler(background_tasks))
    try:
        yield
    finally:
        reset_delivery_scheduler(token)