"""engagement_feedbacks table for participant experience ratings.

Revision ID: 0165_engagement_feedbacks
Revises: 0164_camp_consult_req_otp_intent
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0165_engagement_feedbacks"
down_revision = "0164_camp_consult_req_otp_intent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    overall_rating_enum = postgresql.ENUM(
        "excellent",
        "very_good",
        "good",
        "could_be_better",
        "bad",
        name="engagement_feedback_overall_rating",
        create_type=False,
    )
    overall_rating_enum.create(connection, checkfirst=True)

    op.create_table(
        "engagement_feedbacks",
        sa.Column("feedback_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("engagement_participant_id", sa.Integer(), nullable=False),
        sa.Column("overall_rating", overall_rating_enum, nullable=False),
        sa.Column(
            "category_ratings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("comment", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["engagement_participant_id"],
            ["engagement_participants.engagement_participant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("feedback_id"),
        sa.UniqueConstraint(
            "engagement_participant_id",
            name="uq_engagement_feedbacks_participant",
        ),
    )
    op.create_index(
        "ix_engagement_feedbacks_created_at",
        "engagement_feedbacks",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_engagement_feedbacks_created_at", table_name="engagement_feedbacks")
    op.drop_table("engagement_feedbacks")
    postgresql.ENUM(name="engagement_feedback_overall_rating").drop(op.get_bind(), checkfirst=True)
