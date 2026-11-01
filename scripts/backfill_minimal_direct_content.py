"""Set minimal WhatsApp/email direct-delivery fields on active services that lack them.

Idempotent staging helper before cutover verify. Does not overwrite existing content.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from core.config import settings

_MIN_VARS = json.dumps(
    [{"component": "body", "parameters": [{"type": "text", "source": "{{user.first_name}}"}]}]
)


def _async_database_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


async def _run() -> int:
    url = os.getenv("DATABASE_URL") or settings.DATABASE_URL
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    engine = create_async_engine(_async_database_url(url), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            wa = await conn.execute(
                text(
                    """
                    UPDATE notification_services
                    SET template_name = COALESCE(NULLIF(btrim(template_name), ''), service_key),
                        template_variables = COALESCE(
                            template_variables,
                            CAST(:vars AS jsonb)
                        )
                    WHERE is_active = true
                      AND channel = 'whatsapp'
                      AND (
                        template_name IS NULL OR btrim(template_name) = ''
                        OR template_variables IS NULL
                      )
                    """
                ),
                {"vars": _MIN_VARS},
            )
            em = await conn.execute(
                text(
                    """
                    UPDATE notification_services
                    SET email_subject = COALESCE(NULLIF(btrim(email_subject), ''), display_name),
                        email_body = COALESCE(
                            NULLIF(btrim(email_body), ''),
                            'Notification for {{user.first_name}}'
                        )
                    WHERE is_active = true
                      AND channel = 'email'
                      AND COALESCE(btrim(email_subject), '') = ''
                      AND COALESCE(btrim(email_body), '') = ''
                      AND COALESCE(btrim(email_html), '') = ''
                    """
                )
            )
        print(f"backfill_minimal_direct_content: whatsapp={wa.rowcount} email={em.rowcount}")
        return 0
    finally:
        await engine.dispose()


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
