"""Verify staging DB and env are ready for notification cutover (Prompt 6).

Exit 0 when ready; non-zero with messages on failure.
Run on staging before `alembic upgrade` to revision 0188.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import sqlalchemy as sa
from sqlalchemy import create_engine, text

from core.config import settings


def _sync_database_url(url: str) -> str:
    """Use a synchronous driver for one-off readiness checks."""
    if "+asyncpg" in url:
        return url.replace("postgresql+asyncpg", "postgresql+psycopg2", 1)
    return url


def _engine():
    url = os.getenv("DATABASE_URL") or settings.DATABASE_URL
    if not url:
        raise SystemExit("DATABASE_URL is not set")
    return create_engine(_sync_database_url(url), pool_pre_ping=True)


def main() -> None:
    warnings: list[str] = []
    errors: list[str] = []

    legacy_fb = os.getenv(
        "NOTIFICATION_ENGINE_LEGACY_FALLBACK",
        str(settings.NOTIFICATION_ENGINE_LEGACY_FALLBACK),
    ).lower()
    if legacy_fb in ("1", "true", "yes"):
        errors.append("NOTIFICATION_ENGINE_LEGACY_FALLBACK must be false before cutover")

    engine = _engine()
    with engine.connect() as conn:
        missing_content = conn.execute(
            text(
                """
                SELECT service_key, channel
                FROM notification_services
                WHERE is_active = true
                  AND (
                    (channel = 'whatsapp' AND (
                        template_name IS NULL OR btrim(template_name) = ''
                        OR template_variables IS NULL
                    ))
                    OR (channel = 'email' AND (
                        COALESCE(btrim(email_subject), '') = ''
                        AND COALESCE(btrim(email_body), '') = ''
                        AND COALESCE(btrim(email_html), '') = ''
                    ))
                  )
                ORDER BY service_key
                """
            )
        ).fetchall()
        if missing_content:
            for row in missing_content:
                errors.append(
                    f"Active service '{row.service_key}' ({row.channel}) lacks direct delivery content"
                )

        null_codes = conn.execute(
            text(
                """
                SELECT COUNT(*) AS n
                FROM engagement_notifications
                WHERE event_code IS NULL OR btrim(event_code) = ''
                   OR recipient_type IS NULL OR btrim(recipient_type) = ''
                """
            )
        ).scalar_one()
        if null_codes and int(null_codes) > 0:
            errors.append(
                f"engagement_notifications has {null_codes} row(s) missing event_code or recipient_type"
            )

        recent_missing = conn.execute(
            text(
                """
                SELECT DISTINCT n.service_key
                FROM notifications n
                JOIN notification_services s ON s.service_key = n.service_key
                WHERE n.dispatched_at >= now() - interval '30 days'
                  AND s.is_active = true
                  AND (
                    (s.channel = 'whatsapp' AND (
                        s.template_name IS NULL OR btrim(s.template_name) = ''
                        OR s.template_variables IS NULL
                    ))
                    OR (s.channel = 'email' AND (
                        COALESCE(btrim(s.email_subject), '') = ''
                        AND COALESCE(btrim(s.email_body), '') = ''
                        AND COALESCE(btrim(s.email_html), '') = ''
                    ))
                  )
                ORDER BY 1
                LIMIT 20
                """
            )
        ).fetchall()
        for row in recent_missing:
            warnings.append(
                f"WARN: service '{row.service_key}' used in last 30 days but lacks direct content"
            )

    for w in warnings:
        print(w, file=sys.stderr)
    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)

    if errors:
        raise SystemExit(1)
    print("NOTIFICATION_CUTOVER_READY")


if __name__ == "__main__":
    main()
