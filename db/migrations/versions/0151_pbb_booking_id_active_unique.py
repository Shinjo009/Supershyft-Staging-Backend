"""Unique booking_id only among active participant blood bookings.

Revision ID: 0151_pbb_booking_id_active
Revises: 0150_healthlabs_provider
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0151_pbb_booking_id_active"
down_revision = "0150_healthlabs_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_pbb_booking_id", table_name="participant_blood_bookings")
    op.create_index(
        "uq_pbb_booking_id",
        "participant_blood_bookings",
        ["booking_id"],
        unique=True,
        postgresql_where=sa.text(
            "booking_id IS NOT NULL AND btrim(booking_id) <> '' AND status = 1"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_pbb_booking_id", table_name="participant_blood_bookings")
    op.create_index(
        "uq_pbb_booking_id",
        "participant_blood_bookings",
        ["booking_id"],
        unique=True,
        postgresql_where=sa.text("booking_id IS NOT NULL AND btrim(booking_id) <> ''"),
    )
