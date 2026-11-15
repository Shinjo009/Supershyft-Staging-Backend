"""Merge parallel 0209 heads (users created_at default + drop notif webhook_path)."""

from __future__ import annotations

revision = "0210_merge_0209_heads"
down_revision = ("0209_drop_notif_webhook_path", "0209_users_created_at_default")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass