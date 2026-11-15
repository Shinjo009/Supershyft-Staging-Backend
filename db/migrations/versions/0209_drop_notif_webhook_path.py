"""Drop legacy notification_services.webhook_path (n8n era)."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0209_drop_notif_webhook_path"
down_revision = "0208_notif_whatsapp_msg_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("notification_services", "webhook_path")


def downgrade() -> None:
    op.add_column(
        "notification_services",
        sa.Column("webhook_path", sa.String(), nullable=False, server_default=""),
    )