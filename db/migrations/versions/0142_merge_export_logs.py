"""Merge origin notification heads with staging export_logs.

Revision ID: 0142_merge_export_logs
Revises: 0141_phlebo_webhook_notif, 0140_export_logs
"""

from __future__ import annotations

revision = "0142_merge_export_logs"
down_revision = ("0141_phlebo_webhook_notif", "0140_export_logs")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
