"""Add whatapi to integration_provider_enum for direct send sync logs.

Revision ID: 0177_whatapi_provider
Revises: 0176_notif_rebuild_foundation
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0177_whatapi_provider"
down_revision = "0176_notif_rebuild_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("ALTER TYPE integration_provider_enum ADD VALUE IF NOT EXISTS 'whatapi'"))


def downgrade() -> None:
    pass
