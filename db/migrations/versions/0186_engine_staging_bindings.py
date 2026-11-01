"""Seed minimal global notification event bindings for engine (OTP + support).

Revision ID: 0186_engine_staging_bindings
Revises: 0185_otp_direct_content
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0186_engine_staging_bindings"
down_revision = "0185_otp_direct_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = (
        (
            "auth.otp.sent",
            "OTP sent",
            "participant",
            json.dumps(["whatapi-otp", "email-otp"]),
        ),
        (
            "auth.otp.sent",
            "OTP sent",
            "employee",
            json.dumps(["whatapi-otp", "email-otp"]),
        ),
        (
            "auth.otp.sent",
            "OTP sent",
            "partner",
            json.dumps(["whatapi-otp", "email-otp"]),
        ),
        (
            "support.ticket.created",
            "Support ticket created",
            "admin",
            json.dumps(["support-svc-a", "support-svc-b"]),
        ),
    )
    for event_code, event_name, recipient_type, services_json in rows:
        conn.execute(
            sa.text(
                """
                INSERT INTO notification_events
                    (event_code, event_name, recipient_type, notification_services, is_active)
                VALUES
                    (:event_code, :event_name, :recipient_type, CAST(:services AS jsonb), true)
                ON CONFLICT (event_code, recipient_type) DO UPDATE SET
                    event_name = EXCLUDED.event_name,
                    notification_services = EXCLUDED.notification_services,
                    is_active = true
                """
            ),
            {
                "event_code": event_code,
                "event_name": event_name,
                "recipient_type": recipient_type,
                "services": services_json,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    for event_code, recipient_type in (
        ("auth.otp.sent", "participant"),
        ("auth.otp.sent", "employee"),
        ("auth.otp.sent", "partner"),
        ("support.ticket.created", "admin"),
    ):
        conn.execute(
            sa.text(
                "DELETE FROM notification_events "
                "WHERE event_code = :event_code AND recipient_type = :recipient_type"
            ),
            {"event_code": event_code, "recipient_type": recipient_type},
        )
