"""Seed booking confirmation notification services (require_session_details).

Triggered when Healthians sends status_updated with booking_status BS005
(new booking created). Dispatch must include session_details (date, slot).

Revision ID: 0140_booking_confirmation_notif
Revises: 0139_eng_draft_slot
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0140_booking_confirmation_notif"
down_revision = "0139_eng_draft_slot"
branch_labels = None
depends_on = None

_SERVICE_SEEDS: list[dict] = [
    {
        "service_key": "booking-confirmation-whatsapp",
        "display_name": "Booking Confirmation WhatsApp",
        "channel": "whatsapp",
        "webhook_path": "/booking-confirmation-whatsapp-v1",
        "require_session_details": True,
    },
    {
        "service_key": "booking-confirmation-email",
        "display_name": "Booking Confirmation Email",
        "channel": "email",
        "webhook_path": "/booking-confirmation-email-v1",
        "require_session_details": True,
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
                    false,
                    false,
                    :require_session_details,
                    false
                )
                ON CONFLICT (service_key) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    channel = EXCLUDED.channel,
                    webhook_path = EXCLUDED.webhook_path,
                    is_active = true,
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
