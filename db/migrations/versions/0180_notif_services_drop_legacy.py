"""Drop webhook_path and require_* from notification_services.

Revision ID: 0180_notif_services_drop_legacy
Revises: 0179_notification_events_migrate
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0180_notif_services_drop_legacy"
down_revision = "0179_notification_events_migrate"
branch_labels = None
depends_on = None

_LEGACY_COLUMNS = (
    "webhook_path",
    "require_blood_report_url",
    "require_bio_ai_report_url",
    "require_participant_detail",
    "require_otp",
    "require_session_details",
    "require_external_link",
)


def upgrade() -> None:
    for col in _LEGACY_COLUMNS:
        op.drop_column("notification_services", col)


def downgrade() -> None:
    op.add_column("notification_services", sa.Column("webhook_path", sa.String(), nullable=False, server_default="/legacy"))
    op.add_column(
        "notification_services",
        sa.Column("require_blood_report_url", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "notification_services",
        sa.Column("require_bio_ai_report_url", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "notification_services",
        sa.Column("require_participant_detail", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "notification_services",
        sa.Column("require_otp", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "notification_services",
        sa.Column("require_session_details", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "notification_services",
        sa.Column("require_external_link", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.alter_column("notification_services", "webhook_path", server_default=None)
