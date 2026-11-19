"""Add event_code to notifications for event-level dedupe.

Revision ID: 0217_notifications_event_code
Revises: 0216_report_consult_ts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision = "0217_notifications_event_code"
down_revision = "0216_report_consult_ts"
branch_labels = None
depends_on = None


def _column_exists(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    if table_name not in inspector.get_table_names():
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)

    if not _column_exists(inspector, "notifications", "event_code"):
        op.add_column(
            "notifications",
            sa.Column("event_code", sa.String(), nullable=True),
        )

    op.execute(
        text(
            """
            WITH key_to_event AS (
                SELECT DISTINCT
                    elem->>'service_key' AS service_key,
                    event_code
                FROM notification_events,
                LATERAL jsonb_array_elements(
                    CASE
                        WHEN jsonb_typeof(notification_services::jsonb) = 'array'
                        THEN notification_services::jsonb
                        ELSE '[]'::jsonb
                    END
                ) AS elem
                WHERE COALESCE(elem->>'service_key', '') <> ''
                UNION
                SELECT DISTINCT
                    elem->>'service_key' AS service_key,
                    event_code
                FROM engagement_notifications,
                LATERAL jsonb_array_elements(
                    CASE
                        WHEN jsonb_typeof(notification_services::jsonb) = 'array'
                        THEN notification_services::jsonb
                        ELSE '[]'::jsonb
                    END
                ) AS elem
                WHERE COALESCE(elem->>'service_key', '') <> ''
            ),
            best_map AS (
                SELECT DISTINCT ON (service_key)
                    service_key,
                    event_code
                FROM key_to_event
                WHERE service_key IS NOT NULL AND service_key <> ''
                ORDER BY service_key, event_code
            )
            UPDATE notifications AS n
            SET event_code = m.event_code
            FROM best_map AS m
            WHERE n.service_key = m.service_key
              AND n.event_code IS NULL
            """
        )
    )

    op.create_index(
        "ix_notifications_event_eng_status",
        "notifications",
        ["event_code", "engagement_id", "status"],
        unique=False,
        postgresql_where=sa.text("event_code IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_event_eng_status", table_name="notifications")
    op.drop_column("notifications", "event_code")