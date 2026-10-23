"""n8n template parity: UPSERT notification_services from fixtures; deactivate deprecated keys.

Revision ID: 0185_n8n_template_parity
Revises: 0184_whatapi_otp_otpmsg
"""

from __future__ import annotations

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0185_n8n_template_parity"
down_revision = "0184_whatapi_otp_otpmsg"
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
                INSERT INTO notification_services (
                    service_key,
                    display_name,
                    channel,
                    is_active,
                    template_name,
                    template_variables,
                    email_subject,
                    email_body,
                    email_html
                )
                VALUES (
                    :service_key,
                    :display_name,
                    :channel,
                    :is_active,
                    NULLIF(:template_name, ''),
                    CAST(:template_variables AS jsonb),
                    NULLIF(:email_subject, ''),
                    NULLIF(:email_body, ''),
                    NULLIF(:email_html, '')
                )
                ON CONFLICT (service_key) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    channel = EXCLUDED.channel,
                    is_active = EXCLUDED.is_active,
                    template_name = COALESCE(NULLIF(EXCLUDED.template_name, ''), notification_services.template_name),
                    template_variables = COALESCE(EXCLUDED.template_variables, notification_services.template_variables),
                    email_subject = COALESCE(NULLIF(EXCLUDED.email_subject, ''), notification_services.email_subject),
                    email_body = COALESCE(NULLIF(EXCLUDED.email_body, ''), notification_services.email_body),
                    email_html = COALESCE(NULLIF(EXCLUDED.email_html, ''), notification_services.email_html)
                """
            ),
            {
                "service_key": row["service_key"],
                "display_name": row.get("display_name") or row["service_key"],
                "channel": row["channel"],
                "is_active": row.get("is_active", True),
                "template_name": row.get("template_name") or "",
                "template_variables": json.dumps(row.get("template_variables"))
                if row.get("template_variables") is not None
                else None,
                "email_subject": row.get("email_subject") or "",
                "email_body": row.get("email_body") or "",
                "email_html": row.get("email_html") or "",
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
