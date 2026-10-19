"""Drop vestigial engagement draft_slot_* columns from public/code pay-later flow.

Revision ID: 0166_drop_eng_draft_slot
Revises: 0165_engagement_feedbacks
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0166_drop_eng_draft_slot"
down_revision = "0165_engagement_feedbacks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("engagements", "draft_slot_time")
    op.drop_column("engagements", "draft_slot_date")
    op.drop_column("engagements", "draft_slot_id")


def downgrade() -> None:
    op.add_column("engagements", sa.Column("draft_slot_id", sa.String(), nullable=True))
    op.add_column("engagements", sa.Column("draft_slot_date", sa.Date(), nullable=True))
    op.add_column("engagements", sa.Column("draft_slot_time", sa.Time(), nullable=True))
