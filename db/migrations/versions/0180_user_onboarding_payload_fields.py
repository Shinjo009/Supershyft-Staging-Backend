"""Add user onboarding payload field catalog and per-camp payload rows.

Revision ID: 0180_user_onboarding_payload
Revises: 0179_diag_pkg_default_group
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0180_user_onboarding_payload"
down_revision = "0179_diag_pkg_default_group"
branch_labels = None
depends_on = None

_PAYLOAD_SECTIONS = ("personal_information", "address", "schedule")
_PAYLOAD_INPUT_TYPES = ("number", "text", "json")


def upgrade() -> None:
    section_enum = postgresql.ENUM(*_PAYLOAD_SECTIONS, name="user_onboarding_payload_section")
    input_type_enum = postgresql.ENUM(*_PAYLOAD_INPUT_TYPES, name="user_onboarding_payload_input_type")
    section_enum.create(op.get_bind(), checkfirst=True)
    input_type_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "user_onboarding_payload_fields",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("payload_key", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column(
            "section",
            postgresql.ENUM(name="user_onboarding_payload_section", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "input_type",
            postgresql.ENUM(name="user_onboarding_payload_input_type", create_type=False),
            nullable=False,
        ),
        sa.UniqueConstraint("payload_key", name="uq_user_onboarding_payload_fields_payload_key"),
    )

    op.create_table(
        "camp_user_onboarding_payload_fields",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("camp_no", sa.BigInteger(), nullable=False),
        sa.Column(
            "onboarding_payload",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.UniqueConstraint("camp_no", name="uq_camp_user_onboarding_payload_fields_camp_no"),
    )
    op.create_index(
        "ix_camp_user_onboarding_payload_fields_camp_no",
        "camp_user_onboarding_payload_fields",
        ["camp_no"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_camp_user_onboarding_payload_fields_camp_no",
        table_name="camp_user_onboarding_payload_fields",
    )
    op.drop_table("camp_user_onboarding_payload_fields")
    op.drop_table("user_onboarding_payload_fields")
    postgresql.ENUM(name="user_onboarding_payload_input_type").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="user_onboarding_payload_section").drop(op.get_bind(), checkfirst=True)
