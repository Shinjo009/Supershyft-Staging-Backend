"""Use otpmsg WhatsApp template (2 body params) for whatapi-otp.

Revision ID: 0184_whatapi_otp_otpmsg
Revises: 0183_whatapi_otp_otpv4
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0184_whatapi_otp_otpmsg"
down_revision = "0183_whatapi_otp_otpv4"
branch_labels = None
depends_on = None

_OTPMSG_VARIABLES = json.dumps(["{{otp}}", "verification code"])


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE notification_services
            SET template_name = 'otpmsg',
                template_variables = CAST(:vars AS jsonb)
            WHERE service_key = 'whatapi-otp'
            """
        ),
        {"vars": _OTPMSG_VARIABLES},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE notification_services
            SET template_name = 'otpv4',
                template_variables = CAST(:vars AS jsonb)
            WHERE service_key = 'whatapi-otp'
            """
        ),
        {"vars": json.dumps(["{{otp}}"])},
    )
