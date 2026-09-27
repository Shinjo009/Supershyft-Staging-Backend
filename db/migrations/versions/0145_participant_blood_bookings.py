"""participant_blood_bookings table; migrate schedule/booking/blood from ep and ihr.

Revision ID: 0145_participant_blood_bookings
Revises: 0144_state_disease_benchmark
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql


revision = "0145_participant_blood_bookings"
down_revision = "0144_state_disease_benchmark"
branch_labels = None
depends_on = None


def _column_exists(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    if table_name not in inspector.get_table_names():
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _table_exists(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)

    if not _table_exists(inspector, "participant_blood_bookings"):
        blood_booking_relation_enum = postgresql.ENUM(
            "primary",
            "resample",
            "redraw",
            "reschedule",
            name="blood_booking_relation_enum",
            create_type=False,
        )
        blood_booking_status_enum = postgresql.ENUM(
            "active",
            "superseded",
            "cancelled",
            name="blood_booking_status_enum",
            create_type=False,
        )
        blood_booking_relation_enum.create(connection, checkfirst=True)
        blood_booking_status_enum.create(connection, checkfirst=True)

        op.create_table(
            "participant_blood_bookings",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("engagement_participant_id", sa.Integer(), nullable=False),
            sa.Column("collection_date", sa.Date(), nullable=True),
            sa.Column("collection_cabin", sa.String(), nullable=True),
            sa.Column("collection_time", sa.Time(), nullable=True),
            sa.Column("collection_time_slot_id", sa.String(), nullable=True),
            sa.Column("booking_id", sa.String(), nullable=True),
            sa.Column("barcode", sa.String(), nullable=True),
            sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "relation",
                blood_booking_relation_enum,
                server_default="primary",
                nullable=False,
            ),
            sa.Column("parent_booking_id", sa.String(), nullable=True),
            sa.Column(
                "status",
                blood_booking_status_enum,
                server_default="active",
                nullable=False,
            ),
            sa.Column("diagnostic_report_url", sa.Text(), nullable=True),
            sa.Column("blood_parameters", postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column("blood_report_raw", postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column("blood_parameters_full_report", sa.Boolean(), nullable=True),
            sa.Column("blood_parameters_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["engagement_participant_id"],
                ["engagement_participants.engagement_participant_id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_pbb_engagement_participant_id",
            "participant_blood_bookings",
            ["engagement_participant_id"],
        )
        op.create_index(
            "ix_pbb_cabin_slot_occupancy",
            "participant_blood_bookings",
            ["engagement_participant_id", "collection_cabin", "collection_date", "collection_time"],
        )
        op.create_index(
            "uq_pbb_booking_id",
            "participant_blood_bookings",
            ["booking_id"],
            unique=True,
            postgresql_where=sa.text("booking_id IS NOT NULL AND btrim(booking_id) <> ''"),
        )

    if _column_exists(inspector, "engagement_participants", "booking_id"):
        connection.execute(
            text(
                """
                WITH booking_winners AS (
                    SELECT
                        booking_id,
                        MAX(engagement_participant_id) AS winner_ep_id
                    FROM engagement_participants
                    WHERE booking_id IS NOT NULL AND btrim(booking_id) <> ''
                    GROUP BY booking_id
                ),
                ihr_best AS (
                    SELECT DISTINCT ON (user_id, engagement_id)
                        user_id,
                        engagement_id,
                        diagnostic_report_url,
                        blood_parameters,
                        blood_report_raw,
                        blood_parameters_full_report,
                        blood_parameters_verified_at
                    FROM individual_health_report
                    ORDER BY
                        user_id,
                        engagement_id,
                        (blood_parameters IS NOT NULL) DESC,
                        (diagnostic_report_url IS NOT NULL) DESC,
                        report_id DESC
                )
                INSERT INTO participant_blood_bookings (
                    engagement_participant_id,
                    collection_date,
                    collection_cabin,
                    collection_time,
                    collection_time_slot_id,
                    booking_id,
                    barcode,
                    relation,
                    status,
                    diagnostic_report_url,
                    blood_parameters,
                    blood_report_raw,
                    blood_parameters_full_report,
                    blood_parameters_verified_at
                )
                SELECT
                    ep.engagement_participant_id,
                    ep.engagement_date,
                    ep.blood_collection_cabin,
                    ep.slot_start_time,
                    ep.blood_collection_time_slot_id,
                    CASE
                        WHEN bw.winner_ep_id IS NOT NULL
                             AND bw.winner_ep_id <> ep.engagement_participant_id
                        THEN NULL
                        ELSE NULLIF(btrim(ep.booking_id), '')
                    END,
                    ep.barcode,
                    'primary',
                    'active',
                    ihr.diagnostic_report_url,
                    ihr.blood_parameters,
                    ihr.blood_report_raw,
                    ihr.blood_parameters_full_report,
                    ihr.blood_parameters_verified_at
                FROM engagement_participants ep
                LEFT JOIN booking_winners bw ON bw.booking_id = ep.booking_id
                LEFT JOIN ihr_best ihr
                    ON ihr.user_id = ep.user_id AND ihr.engagement_id = ep.engagement_id
                WHERE
                    (ep.booking_id IS NOT NULL AND btrim(ep.booking_id) <> '')
                    OR (ep.barcode IS NOT NULL AND btrim(ep.barcode) <> '')
                    OR ep.engagement_date IS NOT NULL
                    OR ep.slot_start_time IS NOT NULL
                    OR (
                        ep.blood_collection_time_slot_id IS NOT NULL
                        AND btrim(ep.blood_collection_time_slot_id) <> ''
                    )
                    OR (
                        ep.blood_collection_cabin IS NOT NULL
                        AND btrim(ep.blood_collection_cabin) <> ''
                    )
                """
            )
        )

        op.drop_index("ix_ep_cabin_slot_occupancy", table_name="engagement_participants")
        op.drop_index("ix_engagement_participants_booking_id", table_name="engagement_participants")
        op.drop_index("ix_ep_engagement_date", table_name="engagement_participants")
        op.drop_column("engagement_participants", "blood_collection_cabin")
        op.drop_column("engagement_participants", "blood_collection_time_slot_id")
        op.drop_column("engagement_participants", "booking_id")
        op.drop_column("engagement_participants", "barcode")
        op.drop_column("engagement_participants", "engagement_date")
        op.drop_column("engagement_participants", "slot_start_time")

    inspector = inspect(connection)
    if _column_exists(inspector, "individual_health_report", "blood_parameters"):
        op.drop_column("individual_health_report", "blood_parameters_verified_at")
        op.drop_column("individual_health_report", "blood_parameters_full_report")
        op.drop_column("individual_health_report", "diagnostic_report_url")
        op.drop_column("individual_health_report", "blood_report_raw")
        op.drop_column("individual_health_report", "blood_parameters")


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
