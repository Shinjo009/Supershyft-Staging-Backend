"""Indexes for admin dashboard aggregate queries.

Revision ID: 0161_dashboard_aggregate_indexes
Revises: 0160_booking_expert_consultation
"""

from __future__ import annotations

from alembic import op

revision = "0161_dashboard_aggregate_indexes"
down_revision = "0160_booking_expert_consultation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_pbb_collection_date_status",
        "participant_blood_bookings",
        ["collection_date", "status"],
        unique=False,
    )
    op.create_index(
        "ix_consultation_bookings_date_expert_type",
        "consultation_bookings",
        ["consultation_date", "expert_type"],
        unique=False,
    )
    op.create_index(
        "ix_engagements_status_dates",
        "engagements",
        ["status", "start_date", "end_date"],
        unique=False,
    )
    op.create_index("ix_users_created_at", "users", ["created_at"], unique=False)
    op.create_index("ix_users_status", "users", ["status"], unique=False)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notifications_status_failed "
        "ON notifications (status) WHERE status = 3"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_notifications_status_failed")
    op.drop_index("ix_users_status", table_name="users")
    op.drop_index("ix_users_created_at", table_name="users")
    op.drop_index("ix_engagements_status_dates", table_name="engagements")
    op.drop_index("ix_consultation_bookings_date_expert_type", table_name="consultation_bookings")
    op.drop_index("ix_pbb_collection_date_status", table_name="participant_blood_bookings")
