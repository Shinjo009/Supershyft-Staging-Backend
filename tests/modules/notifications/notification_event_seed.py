"""Shared helpers for notification event binding test fixtures."""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def _service_channel(session: AsyncSession, service_key: str) -> str:
    row = await session.execute(
        text("SELECT channel FROM notification_services WHERE service_key = :sk"),
        {"sk": service_key},
    )
    ch = row.scalar_one_or_none()
    return str(ch or "whatsapp")


async def upsert_engagement_notification(
    session: AsyncSession,
    *,
    engagement_id: int,
    event_code: str,
    service_keys: list[str] | str,
    recipient_type: str = "user",
    condition_key: str = "default",
) -> None:
    if isinstance(service_keys, str):
        keys = [k.strip() for k in service_keys.split(",") if k.strip()]
    else:
        keys = list(service_keys)

    await session.execute(
        text(
            """
            DELETE FROM engagement_notifications
            WHERE engagement_id = :eid AND event_code = :event_code
            """
        ),
        {"eid": engagement_id, "event_code": event_code},
    )

    for key in keys:
        channel = await _service_channel(session, key)
        services_json = json.dumps([{"service_key": key, "external_link": None}])
        await session.execute(
            text(
                """
                INSERT INTO engagement_notifications (
                    engagement_id,
                    event_code,
                    recipient_type,
                    delivery_channel,
                    condition_key,
                    notification_services
                )
                VALUES (:eid, :event_code, :recipient, :channel, :condition, CAST(:services AS jsonb))
                ON CONFLICT ON CONSTRAINT uq_engagement_notification_slot DO UPDATE
                SET notification_services = EXCLUDED.notification_services
                """
            ),
            {
                "eid": engagement_id,
                "event_code": event_code,
                "recipient": recipient_type,
                "channel": channel,
                "condition": condition_key,
                "services": services_json,
            },
        )