"""Fix onboarding.completed global bindings (OA alert + participant welcome).

Revision ID: 0190_onboarding_bindings
Revises: 0189_n8n_templates
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0190_onboarding_bindings"
down_revision = "0189_n8n_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = (
        (
            "onboarding.completed",
            "Onboarding completed",
            "oa.all",
            json.dumps(["booking-alert-whatsapp", "b2b-booking-alert-whatsapp-v1"]),
        ),
        (
            "onboarding.completed",
            "Onboarding completed",
            "participant",
            json.dumps(["welcome-whatsapp", "welcome-email"]),
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
    conn.execute(
        sa.text(
            """
            UPDATE notification_events
            SET notification_services = CAST(:services AS jsonb)
            WHERE event_code = 'onboarding.completed' AND recipient_type = 'oa.all'
            """
        ),
        {"services": json.dumps(["welcome-whatsapp", "welcome-email"])},
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM notification_events
            WHERE event_code = 'onboarding.completed' AND recipient_type = 'participant'
            """
        ),
    )
