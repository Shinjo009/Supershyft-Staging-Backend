"""Cascade family onboard FKs so admin deletes can remove participants.

Revision ID: 0169_family_onboard_cascades
Revises: 0168_family_onboards
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0169_family_onboard_cascades"
down_revision = "0168_family_onboards"
branch_labels = None
depends_on = None


_CASCADE_FKS = (
    ("family_onboards", "booker_user_id", "users", ["user_id"]),
    ("family_onboard_members", "user_id", "users", ["user_id"]),
    ("family_onboard_members", "engagement_id", "engagements", ["engagement_id"]),
    (
        "family_onboard_members",
        "engagement_participant_id",
        "engagement_participants",
        ["engagement_participant_id"],
    ),
)


def _fk_name(inspector: sa.Inspector, table_name: str, column_name: str) -> str | None:
    if table_name not in inspector.get_table_names():
        return None
    for fk in inspector.get_foreign_keys(table_name):
        if fk.get("constrained_columns") == [column_name]:
            return fk.get("name")
    return None


def _recreate_fk(
    inspector: sa.Inspector,
    *,
    table_name: str,
    column_name: str,
    referent_table: str,
    referent_columns: list[str],
    ondelete: str | None,
) -> None:
    if table_name not in inspector.get_table_names():
        return
    existing = _fk_name(inspector, table_name, column_name)
    if existing:
        op.drop_constraint(existing, table_name, type_="foreignkey")
    op.create_foreign_key(
        None,
        table_name,
        referent_table,
        [column_name],
        referent_columns,
        ondelete=ondelete,
    )


def upgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '60s'"))
    inspector = inspect(op.get_bind())
    for table_name, column_name, referent_table, referent_columns in _CASCADE_FKS:
        _recreate_fk(
            inspector,
            table_name=table_name,
            column_name=column_name,
            referent_table=referent_table,
            referent_columns=referent_columns,
            ondelete="CASCADE",
        )
        inspector = inspect(op.get_bind())


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '60s'"))
    inspector = inspect(op.get_bind())
    for table_name, column_name, referent_table, referent_columns in _CASCADE_FKS:
        _recreate_fk(
            inspector,
            table_name=table_name,
            column_name=column_name,
            referent_table=referent_table,
            referent_columns=referent_columns,
            ondelete=None,
        )
        inspector = inspect(op.get_bind())
