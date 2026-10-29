"""Add camp_code to camp_user_onboarding_payload_fields.

Revision ID: 0181_camp_onboarding_camp_code
Revises: 0180_user_onboarding_payload
"""

from __future__ import annotations

import secrets
import string

import sqlalchemy as sa
from alembic import op

revision = "0181_camp_onboarding_camp_code"
down_revision = "0180_user_onboarding_payload"
branch_labels = None
depends_on = None

_CAMP_CODE_LENGTH = 12
_ALPHABET = string.ascii_letters + string.digits


def _generate_camp_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CAMP_CODE_LENGTH))


def upgrade() -> None:
    op.add_column(
        "camp_user_onboarding_payload_fields",
        sa.Column("camp_code", sa.String(length=_CAMP_CODE_LENGTH), nullable=True),
    )

    conn = op.get_bind()
    row_ids = conn.execute(
        sa.text("SELECT id FROM camp_user_onboarding_payload_fields ORDER BY id ASC")
    ).fetchall()
    used: set[str] = set()
    for (row_id,) in row_ids:
        for _ in range(100):
            code = _generate_camp_code()
            if code in used:
                continue
            used.add(code)
            conn.execute(
                sa.text(
                    "UPDATE camp_user_onboarding_payload_fields "
                    "SET camp_code = :camp_code WHERE id = :row_id"
                ),
                {"camp_code": code, "row_id": row_id},
            )
            break
        else:
            raise RuntimeError("Failed to generate unique camp_code during migration backfill")

    op.alter_column(
        "camp_user_onboarding_payload_fields",
        "camp_code",
        existing_type=sa.String(length=_CAMP_CODE_LENGTH),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_camp_user_onboarding_payload_fields_camp_code",
        "camp_user_onboarding_payload_fields",
        ["camp_code"],
    )
    op.create_index(
        "ix_camp_user_onboarding_payload_fields_camp_code",
        "camp_user_onboarding_payload_fields",
        ["camp_code"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_camp_user_onboarding_payload_fields_camp_code",
        table_name="camp_user_onboarding_payload_fields",
    )
    op.drop_constraint(
        "uq_camp_user_onboarding_payload_fields_camp_code",
        "camp_user_onboarding_payload_fields",
        type_="unique",
    )
    op.drop_column("camp_user_onboarding_payload_fields", "camp_code")
