"""Add draft slot columns for public B2C pay-later booking flow.

Revision ID: 0139_eng_draft_slot
Revises: 0138_ihr_unique_assessment
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0139_eng_draft_slot"
down_revision = "0138_ihr_unique_assessment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("engagements", sa.Column("draft_slot_id", sa.String(), nullable=True))
    op.add_column("engagements", sa.Column("draft_slot_date", sa.Date(), nullable=True))
    op.add_column("engagements", sa.Column("draft_slot_time", sa.Time(), nullable=True))


def downgrade() -> None:
    op.drop_column("engagements", "draft_slot_time")
    op.drop_column("engagements", "draft_slot_date")
    op.drop_column("engagements", "draft_slot_id")
