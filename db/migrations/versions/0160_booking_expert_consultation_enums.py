"""Add expert entity and consultation booking type for paid consultations.

Revision ID: 0160_booking_expert_consultation
Revises: 0159_test_group_forked_from
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0160_booking_expert_consultation"
down_revision = "0159_test_group_forked_from"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("ALTER TYPE booking_entity_type_enum ADD VALUE IF NOT EXISTS 'expert'"))
    op.execute(text("ALTER TYPE booking_type_enum ADD VALUE IF NOT EXISTS 'consultation'"))


def downgrade() -> None:
    # PostgreSQL does not support removing enum values safely; no-op.
    pass
