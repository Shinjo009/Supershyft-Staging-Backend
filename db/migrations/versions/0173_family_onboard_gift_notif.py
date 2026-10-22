"""Seed family-onboard Diwali gift notification services.

Dispatched after family-onboard confirm-payment (booker + receiver WhatsApp/email).

Revision ID: 0173_family_onboard_gift_notif
Revises: 0172_diag_test_group_screening
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0173_family_onboard_gift_notif"
down_revision = "0172_diag_test_group_screening"
branch_labels = None
depends_on = None

_SERVICE_SEEDS: list[dict] = [
    {
        "service_key": "family-onboard-sender-whatsapp",
        "display_name": "Family Onboard Gift Sender WhatsApp",
        "channel": "whatsapp",
        "webhook_path": "/family-onboard-sender-whatsapp-v1",
        "require_participant_detail": True,
    },
    {
        "service_key": "family-onboard-sender-email",
        "display_name": "Family Onboard Gift Sender Email",
        "channel": "email",
        "webhook_path": "/family-onboard-sender-email-v1",
        "require_participant_detail": True,
    },
    {
        "service_key": "family-onboard-receiver-whatsapp",
        "display_name": "Family Onboard Gift Receiver WhatsApp",
        "channel": "whatsapp",
        "webhook_path": "/family-onboard-receiver-whatsapp-v1",
        "require_participant_detail": True,
    },
    {
        "service_key": "family-onboard-receiver-email",
        "display_name": "Family Onboard Gift Receiver Email",
        "channel": "email",
        "webhook_path": "/family-onboard-receiver-email-v1",
        "require_participant_detail": True,
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
                    false,
                    false
                )
                ON CONFLICT (service_key) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    channel = EXCLUDED.channel,
                    webhook_path = EXCLUDED.webhook_path,
                    is_active = true,
                    require_participant_detail = EXCLUDED.require_participant_detail
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
