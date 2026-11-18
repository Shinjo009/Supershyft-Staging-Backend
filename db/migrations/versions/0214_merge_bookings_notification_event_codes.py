"""Rename booking/consultation notification event codes under bookings.blood_test.* and bookings.consultation.*."""

from __future__ import annotations

from alembic import op

from modules.notifications.event_code_merge import (
    apply_event_code_renames,
    dedupe_binding_slots,
    purge_obsolete_event_rows,
    purge_unreferenced_orphan_services,
)

revision = "0214_bookings_event_merge"
down_revision = "0213_strict_eng_notif"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    apply_event_code_renames(conn)
    dedupe_binding_slots(conn)
    purge_obsolete_event_rows(conn)
    purge_unreferenced_orphan_services(conn)


def downgrade() -> None:
    pass