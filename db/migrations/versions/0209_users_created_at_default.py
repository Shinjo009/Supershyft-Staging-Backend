"""Set server default now() on users.created_at (column stays nullable for backfill)."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0209_users_created_at_default"
down_revision = "0208_notif_whatsapp_msg_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=True,
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=True,
        server_default=None,
    )