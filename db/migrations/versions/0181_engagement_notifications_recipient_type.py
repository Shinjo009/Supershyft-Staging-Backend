"""Add recipient_type to engagement_notifications.

Revision ID: 0181_engagement_notifications_recipient_type
Revises: 0180_notif_services_drop_legacy
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0181_eng_notif_recipient_type"
down_revision = "0180_notif_services_drop_legacy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "engagement_notifications",
        sa.Column("recipient_type", sa.String(), nullable=True),
    )
    op.execute(
        """
        UPDATE engagement_notifications en
        SET recipient_type = COALESCE(
            (
                SELECT ne.recipient_type
                FROM notification_events ne
                WHERE ne.event_code = en.event_code
                ORDER BY ne.id
                LIMIT 1
            ),
            'participant'
        )
        """
    )
    op.alter_column("engagement_notifications", "recipient_type", nullable=False)
    op.drop_constraint(
        "uq_engagement_notification_event_code",
        "engagement_notifications",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_engagement_notification_event_recipient",
        "engagement_notifications",
        ["engagement_id", "event_code", "recipient_type"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_engagement_notification_event_recipient",
        "engagement_notifications",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_engagement_notification_event_code",
        "engagement_notifications",
        ["engagement_id", "event_code"],
    )
    op.drop_column("engagement_notifications", "recipient_type")
