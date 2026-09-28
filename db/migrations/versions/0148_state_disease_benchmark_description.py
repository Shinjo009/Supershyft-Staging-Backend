"""Update state_disease_benchmark section description for states[] payload.

Revision ID: 0148_sdb_description
Revises: 0147_user_addresses, 0147_eng_gender_dx_pkg
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "0148_sdb_description"
down_revision = ("0147_user_addresses", "0147_eng_gender_dx_pkg")
branch_labels = None
depends_on = None

_NEW_DESCRIPTION = (
    "Compare company Bio-AI disease and oxidative risk averages with the average "
    "of other Bio-AI-tested companies in each state."
)


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        text(
            """
            UPDATE camp_report_sections
            SET description = :description
            WHERE section_key = 'state_disease_benchmark'
            """
        ),
        {"description": _NEW_DESCRIPTION},
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
