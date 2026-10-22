"""Preflight checks before removing n8n workflow artifacts."""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from db.session import async_session_factory


async def _run() -> int:
    errors: list[str] = []
    async with async_session_factory() as db:
        missing = await db.execute(
            text(
                """
                SELECT service_key FROM notification_services
                WHERE is_active = true
                  AND COALESCE(TRIM(template_name), '') = ''
                  AND COALESCE(TRIM(email_subject), '') = ''
                  AND COALESCE(TRIM(email_body), '') = ''
                  AND COALESCE(TRIM(email_html), '') = ''
                """
            )
        )
        for row in missing.fetchall():
            errors.append(f"Active service '{row[0]}' has no template/email content")

        orphan_en = await db.execute(
            text(
                """
                SELECT DISTINCT (elem->>'service_key') AS sk
                FROM engagement_notifications en,
                     jsonb_array_elements(
                       CASE jsonb_typeof(en.notification_services::jsonb)
                         WHEN 'array' THEN en.notification_services::jsonb
                         ELSE '[]'::jsonb END
                     ) elem
                WHERE NOT EXISTS (
                  SELECT 1 FROM notification_services ns WHERE ns.service_key = elem->>'service_key'
                )
                """
            )
        )
        for row in orphan_en.fetchall():
            if row[0]:
                errors.append(f"engagement_notifications references unknown service_key '{row[0]}'")

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    print("Notification migration preflight OK")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
