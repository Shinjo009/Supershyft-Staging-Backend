"""Add superclub permission category for employee RBAC.

Revision ID: 0177_superclub_permission_category
Revises: 0176_blog_permission_category
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0177_superclub_perm"
down_revision = "0176_blog_permission_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO permission_categories (category_key, display_name, description, display_order, is_active)
            VALUES (
              'superclub',
              'Super Club',
              'Super Club sports playlists and early-access demand',
              (SELECT COALESCE(MAX(display_order), 0) + 1 FROM permission_categories),
              true
            )
            ON CONFLICT (category_key) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported for 0177_superclub_permission_category")
