"""Camp consultation expert ask-request OTP context table.

Revision ID: 0163_camp_consult_req_otp
Revises: 0162_ep_drop_sync_flags
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0163_camp_consult_req_otp"
down_revision = "0162_ep_drop_sync_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "camp_consultation_request_otp_contexts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("auth_otp_session_id", sa.Integer(), nullable=False),
        sa.Column("engagement_id", sa.Integer(), nullable=False),
        sa.Column("engagement_participant_id", sa.Integer(), nullable=False),
        sa.Column("expert_type", sa.String(length=100), nullable=False),
        sa.Column("consent", sa.JSON(), nullable=False),
        sa.Column("initiated_by_partner_id", sa.Integer(), nullable=True),
        sa.Column("initiated_by_employee_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["engagement_id"], ["engagements.engagement_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["engagement_participant_id"],
            ["engagement_participants.engagement_participant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_camp_consult_req_otp_engagement_participant",
        "camp_consultation_request_otp_contexts",
        ["engagement_id", "engagement_participant_id"],
        unique=False,
    )
    op.create_index(
        "ix_camp_consult_req_otp_session",
        "camp_consultation_request_otp_contexts",
        ["auth_otp_session_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_camp_consult_req_otp_session", table_name="camp_consultation_request_otp_contexts")
    op.drop_index(
        "ix_camp_consult_req_otp_engagement_participant",
        table_name="camp_consultation_request_otp_contexts",
    )
    op.drop_table("camp_consultation_request_otp_contexts")
