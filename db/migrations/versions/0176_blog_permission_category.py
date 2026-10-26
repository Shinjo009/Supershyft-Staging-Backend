"""Add blog permission category for employee RBAC.

Revision ID: 0176_blog_permission_category
Revises: 0175_authors_partner_only
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0176_blog_permission_category"
down_revision = "0175_authors_partner_only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO permission_categories (category_key, display_name, description, display_order, is_active)
            VALUES (
              'blog',
              'Blogs',
              'Blog posts, categories, and media uploads',
              (SELECT COALESCE(MAX(display_order), 0) + 1 FROM permission_categories),
              true
            )
            ON CONFLICT (category_key) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported for 0176_blog_permission_category")
