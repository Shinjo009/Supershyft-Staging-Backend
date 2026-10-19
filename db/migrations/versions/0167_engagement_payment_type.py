"""Add engagement payment_type, auto_booking, participant paid and booker_message.

Revision ID: 0167_engagement_payment
Revises: 0166_drop_eng_draft_slot
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0167_engagement_payment"
down_revision = "0166_drop_eng_draft_slot"
branch_labels = None
depends_on = None


def _column_exists(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    if table_name not in inspector.get_table_names():
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '60s'"))
    connection = op.get_bind()
    inspector = inspect(connection)

    payment_type_enum = sa.Enum(
        "paid_by_group",
        "paid_by_patient",
        name="engagement_payment_type",
    )
    payment_type_enum.create(connection, checkfirst=True)

    if not _column_exists(inspector, "engagements", "payment_type"):
        op.add_column(
            "engagements",
            sa.Column(
                "payment_type",
                payment_type_enum,
                nullable=False,
                server_default="paid_by_group",
            ),
        )

    op.execute(
        sa.text(
            """
            UPDATE engagements
            SET payment_type = 'paid_by_group'::engagement_payment_type
            WHERE payment_type IS NULL
            """
        )
    )

    op.execute(
        sa.text(
            """
            ALTER TABLE engagement_participants
            ADD COLUMN IF NOT EXISTS paid BOOLEAN NOT NULL DEFAULT true
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE engagement_participants
            SET paid = true
            WHERE paid IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE engagements
            ADD COLUMN IF NOT EXISTS auto_booking BOOLEAN DEFAULT false
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE engagement_participants
            ADD COLUMN IF NOT EXISTS booker_message VARCHAR(1000)
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '15s'"))
    op.execute(sa.text("ALTER TABLE engagement_participants DROP COLUMN IF EXISTS booker_message"))
    op.execute(sa.text("ALTER TABLE engagements DROP COLUMN IF EXISTS auto_booking"))
    op.execute(sa.text("ALTER TABLE engagement_participants DROP COLUMN IF EXISTS paid"))
    op.execute(sa.text("ALTER TABLE engagements DROP COLUMN IF EXISTS payment_type"))
    op.execute(sa.text("DROP TYPE IF EXISTS engagement_payment_type"))
