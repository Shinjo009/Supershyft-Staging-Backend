"""Drop family onboard cart tables.

Revision ID: 0170_drop_family_onboards
Revises: 0169_family_onboard_cascades
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0170_drop_family_onboards"
down_revision = "0169_family_onboard_cascades"
branch_labels = None
depends_on = None


def _table_exists(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '60s'"))
    connection = op.get_bind()
    inspector = inspect(connection)

    if _table_exists(inspector, "family_onboard_members"):
        op.drop_table("family_onboard_members")
    if _table_exists(inspector, "family_onboards"):
        op.drop_table("family_onboards")


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '60s'"))
    connection = op.get_bind()
    inspector = inspect(connection)

    if not _table_exists(inspector, "family_onboards"):
        op.create_table(
            "family_onboards",
            sa.Column("family_onboard_id", sa.String(length=36), primary_key=True),
            sa.Column(
                "booker_user_id",
                sa.Integer(),
                sa.ForeignKey("users.user_id"),
                nullable=False,
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'pending_payment'"),
            ),
            sa.Column("discount_code", sa.String(length=64), nullable=True),
            sa.Column("razorpay_order_id", sa.String(length=64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_family_onboards_booker_user_id", "family_onboards", ["booker_user_id"])

    if not _table_exists(inspector, "family_onboard_members"):
        op.create_table(
            "family_onboard_members",
            sa.Column("family_onboard_member_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "family_onboard_id",
                sa.String(length=36),
                sa.ForeignKey("family_onboards.family_onboard_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.user_id"), nullable=False),
            sa.Column(
                "engagement_id",
                sa.Integer(),
                sa.ForeignKey("engagements.engagement_id"),
                nullable=False,
            ),
            sa.Column(
                "engagement_participant_id",
                sa.Integer(),
                sa.ForeignKey("engagement_participants.engagement_participant_id"),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "family_onboard_id",
                "user_id",
                name="uq_family_onboard_members_session_user",
            ),
            sa.UniqueConstraint(
                "family_onboard_id",
                "engagement_participant_id",
                name="uq_family_onboard_members_session_participant",
            ),
        )
        op.create_index(
            "ix_family_onboard_members_family_onboard_id",
            "family_onboard_members",
            ["family_onboard_id"],
        )
