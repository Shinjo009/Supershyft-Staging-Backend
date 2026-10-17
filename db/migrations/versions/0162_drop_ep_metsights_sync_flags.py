"""Drop redundant Metsights sync booleans from engagement_participants.

Revision ID: 0162_ep_drop_sync_flags
Revises: 0161_dashboard_aggregate_indexes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0162_ep_drop_sync_flags"
down_revision = "0161_dashboard_aggregate_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("engagement_participants", "is_fitprint_record_id_synced")
    op.drop_column("engagement_participants", "is_primary_record_id_synced")
    op.drop_column("engagement_participants", "is_profile_created_on_metsights")


def downgrade() -> None:
    op.add_column(
        "engagement_participants",
        sa.Column("is_profile_created_on_metsights", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "engagement_participants",
        sa.Column("is_primary_record_id_synced", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "engagement_participants",
        sa.Column("is_fitprint_record_id_synced", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
