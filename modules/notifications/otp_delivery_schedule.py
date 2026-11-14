"""Schedule OTP notification emit without blocking HTTP responses."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.auth.service import OtpDelivery
from modules.notifications.delivery_scheduler import get_delivery_scheduler

if TYPE_CHECKING:
    from modules.auth.service import AuthService


async def schedule_auth_otp_deliveries(
    *,
    auth_service: AuthService,
    db: AsyncSession,
    deliveries: list[OtpDelivery],
    request_phone: str | None = None,
    request_email: str | None = None,
    notify_all_channels: bool = False,
) -> None:
    scheduler = get_delivery_scheduler()

    async def _deliver_all(session: AsyncSession) -> None:
        for delivery in deliveries:
            await auth_service.deliver_otp_via_notifications(
                session,
                delivery=delivery,
                request_phone=request_phone,
                request_email=request_email,
                notify_all_channels=notify_all_channels,
            )

    await scheduler.invoke(_deliver_all, db=db)


async def schedule_staff_otp_delivery(
    *,
    deliver_fn,
    db: AsyncSession,
    **kwargs: Any,
) -> None:
    """deliver_fn(db, **kwargs) — employee/partner auth deliver_otp."""

    scheduler = get_delivery_scheduler()

    async def _work(session: AsyncSession) -> None:
        await deliver_fn(session, **kwargs)

    await scheduler.invoke(_work, db=db)