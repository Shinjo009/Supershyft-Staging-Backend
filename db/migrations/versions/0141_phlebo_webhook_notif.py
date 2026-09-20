"""Seed phlebo webhook notification services.

Revision ID: 0141_phlebo_webhook_notif
Revises: 0140_booking_confirmation_notif
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0141_phlebo_webhook_notif"
down_revision = "0140_booking_confirmation_notif"
branch_labels = None
depends_on = None

_SERVICE_SEEDS: list[dict] = [
    {
        "service_key": "phlebo-assigned-whatsapp",
        "display_name": "Phlebo Assigned WhatsApp",
        "channel": "whatsapp",
        "webhook_path": "/phlebo-assigned-whatsapp-v1",
        "require_participant_detail": True,
        "require_session_details": True,
    },
    {
        "service_key": "phlebo-assigned-email",
        "display_name": "Phlebo Assigned Email",
        "channel": "email",
        "webhook_path": "/phlebo-assigned-email-v1",
        "require_participant_detail": True,
        "require_session_details": True,
    },
    {
        "service_key": "phlebo-reassigned-whatsapp",
        "display_name": "Phlebo Reassigned WhatsApp",
        "channel": "whatsapp",
        "webhook_path": "/phlebo-reassigned-whatsapp-v1",
        "require_participant_detail": True,
        "require_session_details": True,
    },
    {
        "service_key": "phlebo-reassigned-email",
        "display_name": "Phlebo Reassigned Email",
        "channel": "email",
        "webhook_path": "/phlebo-reassigned-email-v1",
        "require_participant_detail": True,
        "require_session_details": True,
    },
    {
        "service_key": "phlebo-enroute-whatsapp",
        "display_name": "Phlebo Enroute WhatsApp",
        "channel": "whatsapp",
        "webhook_path": "/phlebo-enroute-whatsapp-v1",
        "require_participant_detail": True,
        "require_session_details": False,
    },
    {
        "service_key": "phlebo-enroute-email",
        "display_name": "Phlebo Enroute Email",
        "channel": "email",
        "webhook_path": "/phlebo-enroute-email-v1",
        "require_participant_detail": True,
        "require_session_details": False,
    },
    {
        "service_key": "phlebo-delay-whatsapp",
        "display_name": "Phlebo Delay WhatsApp",
        "channel": "whatsapp",
        "webhook_path": "/phlebo-delay-whatsapp-v1",
        "require_participant_detail": True,
        "require_session_details": False,
    },
    {
        "service_key": "phlebo-delay-email",
        "display_name": "Phlebo Delay Email",
        "channel": "email",
        "webhook_path": "/phlebo-delay-email-v1",
        "require_participant_detail": True,
        "require_session_details": False,
    },
]


def upgrade() -> None:
    conn = op.get_bind()
    for svc in _SERVICE_SEEDS:
        conn.execute(
            sa.text(
                """
                INSERT INTO notification_services (
                    service_key,
                    display_name,
                    channel,
                    webhook_path,
                    is_active,
                    require_blood_report_url,
                    require_bio_ai_report_url,
                    require_participant_detail,
                    require_otp,
                    require_session_details,
                    require_external_link
                ) VALUES (
                    :service_key,
                    :display_name,
                    :channel,
                    :webhook_path,
                    true,
                    false,
                    false,
                    :require_participant_detail,
                    false,
                    :require_session_details,
                    false
                )
                ON CONFLICT (service_key) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    channel = EXCLUDED.channel,
                    webhook_path = EXCLUDED.webhook_path,
                    is_active = true,
                    require_participant_detail = EXCLUDED.require_participant_detail,
                    require_session_details = EXCLUDED.require_session_details
                """
            ),
            svc,
        )


def downgrade() -> None:
    conn = op.get_bind()
    for svc in _SERVICE_SEEDS:
        conn.execute(
            sa.text("DELETE FROM notification_services WHERE service_key = :service_key"),
            {"service_key": svc["service_key"]},
        )
