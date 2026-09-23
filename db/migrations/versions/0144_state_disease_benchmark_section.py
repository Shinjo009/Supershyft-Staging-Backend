"""Seed state_disease_benchmark camp report section.

Revision ID: 0144_state_disease_benchmark
Revises: 0143_server_health_host_state
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "0144_state_disease_benchmark"
down_revision = "0143_server_health_host_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        text(
            """
            INSERT INTO camp_report_sections (section_key, section, description)
            VALUES (
                'state_disease_benchmark',
                'State Disease Benchmark',
                'Compare company Bio-AI disease and oxidative risk averages with the average of other Bio-AI-tested companies in the same state.'
            )
            ON CONFLICT (section_key) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
