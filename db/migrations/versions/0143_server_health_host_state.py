"""Persist latest health_check.sh metrics and CPU alert latch.

Revision ID: 0143_server_health_host_state
Revises: 0142_merge_export_logs
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0143_server_health_host_state"
down_revision = "0142_merge_export_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "server_health_host_state",
        sa.Column("hostname", sa.String(255), primary_key=True),
        sa.Column("cpu_usage", sa.Float(), nullable=False),
        sa.Column("memory_usage", sa.Float(), nullable=False),
        sa.Column("storage_usage", sa.Float(), nullable=False),
        sa.Column("load_1m", sa.Float(), nullable=False),
        sa.Column("cores", sa.Integer(), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_alerting", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_recovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_alert_notification_id", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_server_health_host_state_reported_at",
        "server_health_host_state",
        ["reported_at"],
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
