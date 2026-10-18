"""Add intent to camp consultation OTP contexts (request vs consent).

Revision ID: 0164_camp_consult_req_otp_intent
Revises: 0163_camp_consult_req_otp
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0164_camp_consult_req_otp_intent"
down_revision = "0163_camp_consult_req_otp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "camp_consultation_request_otp_contexts",
        sa.Column("intent", sa.String(length=32), nullable=False, server_default="request"),
    )
    op.alter_column(
        "camp_consultation_request_otp_contexts",
        "intent",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("camp_consultation_request_otp_contexts", "intent")
