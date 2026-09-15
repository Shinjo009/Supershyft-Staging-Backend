"""Deduplicate IHR rows and enforce one row per assessment_instance_id.

Revision ID: 0138_ihr_unique_assessment
Revises: 0137_discount_module
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0138_ihr_unique_assessment"
down_revision = "0137_discount_module"
branch_labels = None
depends_on = None


def _index_exists(inspector: sa.Inspector, table: str, name: str) -> bool:
    return any(idx.get("name") == name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Merge duplicate rows per assessment_instance_id, then delete losers.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                report_id,
                assessment_instance_id,
                reports,
                report_url,
                blood_parameters,
                blood_report_raw,
                diagnostic_report_url,
                blood_parameters_full_report,
                blood_parameters_verified_at,
                ROW_NUMBER() OVER (
                    PARTITION BY assessment_instance_id
                    ORDER BY
                        (report_url IS NOT NULL AND report_url <> '') DESC,
                        blood_parameters IS NOT NULL DESC,
                        (diagnostic_report_url IS NOT NULL AND diagnostic_report_url <> '') DESC,
                        report_id DESC
                ) AS rn
            FROM individual_health_report
            WHERE assessment_instance_id IS NOT NULL
        ),
        winners AS (
            SELECT report_id AS winner_id, assessment_instance_id
            FROM ranked
            WHERE rn = 1
        ),
        merged AS (
            SELECT
                w.winner_id,
                COALESCE(
                    w_row.reports,
                    (
                        SELECT r.reports
                        FROM ranked r
                        WHERE r.assessment_instance_id = w.assessment_instance_id
                          AND r.rn > 1
                          AND r.reports IS NOT NULL
                        ORDER BY r.rn
                        LIMIT 1
                    )
                ) AS merged_reports,
                COALESCE(
                    NULLIF(w_row.report_url, ''),
                    (
                        SELECT NULLIF(r.report_url, '')
                        FROM ranked r
                        WHERE r.assessment_instance_id = w.assessment_instance_id
                          AND r.rn > 1
                          AND r.report_url IS NOT NULL
                          AND r.report_url <> ''
                        ORDER BY r.rn
                        LIMIT 1
                    )
                ) AS merged_report_url,
                COALESCE(
                    w_row.blood_parameters,
                    (
                        SELECT r.blood_parameters
                        FROM ranked r
                        WHERE r.assessment_instance_id = w.assessment_instance_id
                          AND r.rn > 1
                          AND r.blood_parameters IS NOT NULL
                        ORDER BY r.rn
                        LIMIT 1
                    )
                ) AS merged_blood_parameters,
                COALESCE(
                    w_row.blood_report_raw,
                    (
                        SELECT r.blood_report_raw
                        FROM ranked r
                        WHERE r.assessment_instance_id = w.assessment_instance_id
                          AND r.rn > 1
                          AND r.blood_report_raw IS NOT NULL
                        ORDER BY r.rn
                        LIMIT 1
                    )
                ) AS merged_blood_report_raw,
                COALESCE(
                    NULLIF(w_row.diagnostic_report_url, ''),
                    (
                        SELECT NULLIF(r.diagnostic_report_url, '')
                        FROM ranked r
                        WHERE r.assessment_instance_id = w.assessment_instance_id
                          AND r.rn > 1
                          AND r.diagnostic_report_url IS NOT NULL
                          AND r.diagnostic_report_url <> ''
                        ORDER BY r.rn
                        LIMIT 1
                    )
                ) AS merged_diagnostic_report_url,
                COALESCE(
                    w_row.blood_parameters_full_report,
                    (
                        SELECT r.blood_parameters_full_report
                        FROM ranked r
                        WHERE r.assessment_instance_id = w.assessment_instance_id
                          AND r.rn > 1
                          AND r.blood_parameters_full_report IS NOT NULL
                        ORDER BY r.rn
                        LIMIT 1
                    )
                ) AS merged_blood_parameters_full_report,
                COALESCE(
                    w_row.blood_parameters_verified_at,
                    (
                        SELECT r.blood_parameters_verified_at
                        FROM ranked r
                        WHERE r.assessment_instance_id = w.assessment_instance_id
                          AND r.rn > 1
                          AND r.blood_parameters_verified_at IS NOT NULL
                        ORDER BY r.rn
                        LIMIT 1
                    )
                ) AS merged_blood_parameters_verified_at
            FROM winners w
            JOIN individual_health_report w_row ON w_row.report_id = w.winner_id
        )
        UPDATE individual_health_report ihr
        SET
            reports = m.merged_reports,
            report_url = m.merged_report_url,
            blood_parameters = m.merged_blood_parameters,
            blood_report_raw = m.merged_blood_report_raw,
            diagnostic_report_url = m.merged_diagnostic_report_url,
            blood_parameters_full_report = m.merged_blood_parameters_full_report,
            blood_parameters_verified_at = m.merged_blood_parameters_verified_at
        FROM merged m
        WHERE ihr.report_id = m.winner_id
        """
    )

    op.execute(
        """
        DELETE FROM individual_health_report
        WHERE report_id IN (
            SELECT report_id
            FROM (
                SELECT
                    report_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY assessment_instance_id
                        ORDER BY
                            (report_url IS NOT NULL AND report_url <> '') DESC,
                            blood_parameters IS NOT NULL DESC,
                            (diagnostic_report_url IS NOT NULL AND diagnostic_report_url <> '') DESC,
                            report_id DESC
                    ) AS rn
                FROM individual_health_report
                WHERE assessment_instance_id IS NOT NULL
            ) ranked
            WHERE rn > 1
        )
        """
    )

    if _index_exists(inspector, "individual_health_report", "ix_ihr_assessment_instance_id"):
        op.drop_index(
            "ix_ihr_assessment_instance_id",
            table_name="individual_health_report",
        )

    if not _index_exists(inspector, "individual_health_report", "uq_ihr_assessment_instance_id"):
        op.create_index(
            "uq_ihr_assessment_instance_id",
            "individual_health_report",
            ["assessment_instance_id"],
            unique=True,
            postgresql_where=sa.text("assessment_instance_id IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _index_exists(inspector, "individual_health_report", "uq_ihr_assessment_instance_id"):
        op.drop_index(
            "uq_ihr_assessment_instance_id",
            table_name="individual_health_report",
        )

    if not _index_exists(inspector, "individual_health_report", "ix_ihr_assessment_instance_id"):
        op.create_index(
            "ix_ihr_assessment_instance_id",
            "individual_health_report",
            ["assessment_instance_id"],
            postgresql_where=sa.text("assessment_instance_id IS NOT NULL"),
        )
