"""Add strict_engagement_notification_bindings to platform_settings.

Revision ID: 0213_strict_eng_notif
Revises: 0212_profile_variants
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0213_strict_eng_notif"
down_revision = "0212_profile_variants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "platform_settings",
        sa.Column(
            "strict_engagement_notification_bindings",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("platform_settings", "strict_engagement_notification_bindings")