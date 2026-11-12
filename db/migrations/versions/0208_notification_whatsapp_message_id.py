"""Add whatsapp_message_id on notifications for Meta delivery webhooks."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0208_notif_whatsapp_msg_id"
down_revision = "0207_drop_legacy_en_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("whatsapp_message_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_notifications_whatsapp_message_id",
        "notifications",
        ["whatsapp_message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_whatsapp_message_id", table_name="notifications")
    op.drop_column("notifications", "whatsapp_message_id")
