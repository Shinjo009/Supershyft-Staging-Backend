"""Point whatapi-otp at approved WABA template otpv4 (otp_new is REJECTED).

Revision ID: 0183_whatapi_otp_otpv4
Revises: 0182_notif_content_backfill
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0183_whatapi_otp_otpv4"
down_revision = "0182_notif_content_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE notification_services
            SET template_name = 'otpv4'
            WHERE service_key = 'whatapi-otp'
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE notification_services
            SET template_name = 'otp_new'
            WHERE service_key = 'whatapi-otp'
            """
        )
    )
