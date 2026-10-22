"""Backfill notification_services content and platform notification_events from fixtures.

Revision ID: 0182_notif_content_backfill
Revises: 0181_eng_notif_recipient_type
"""

from __future__ import annotations

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0182_notif_content_backfill"
down_revision = "0181_eng_notif_recipient_type"
branch_labels = None
depends_on = None

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def _load_json(name: str) -> list[dict]:
    path = _FIXTURES / name
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def upgrade() -> None:
    conn = op.get_bind()
    services = _load_json("notification_services_content.json")
    for row in services:
        conn.execute(
            sa.text(
                """
                UPDATE notification_services
                SET template_name = COALESCE(NULLIF(:template_name, ''), template_name),
                    template_variables = COALESCE(CAST(:template_variables AS jsonb), template_variables),
                    email_subject = COALESCE(NULLIF(:email_subject, ''), email_subject),
                    email_body = COALESCE(NULLIF(:email_body, ''), email_body),
                    email_html = COALESCE(NULLIF(:email_html, ''), email_html),
                    display_name = COALESCE(NULLIF(:display_name, ''), display_name),
                    is_active = COALESCE(:is_active, is_active)
                WHERE service_key = :service_key
                """
            ),
            {
                "service_key": row["service_key"],
                "template_name": row.get("template_name") or "",
                "template_variables": json.dumps(row.get("template_variables"))
                if row.get("template_variables") is not None
                else None,
                "email_subject": row.get("email_subject") or "",
                "email_body": row.get("email_body") or "",
                "email_html": row.get("email_html") or "",
                "display_name": row.get("display_name") or "",
                "is_active": row.get("is_active", True),
            },
        )

    events = _load_json("notification_events_platform_defaults.json")
    for row in events:
        conn.execute(
            sa.text(
                """
                INSERT INTO notification_events
                    (event_code, event_name, recipient_type, notification_services)
                VALUES (:event_code, :event_name, :recipient_type, CAST(:services AS jsonb))
                ON CONFLICT (event_code, recipient_type) DO UPDATE
                SET notification_services = EXCLUDED.notification_services,
                    event_name = EXCLUDED.event_name
                """
            ),
            {
                "event_code": row["event_code"],
                "event_name": row["event_name"],
                "recipient_type": row["recipient_type"],
                "services": json.dumps(row["notification_services"]),
            },
        )


def downgrade() -> None:
    pass
