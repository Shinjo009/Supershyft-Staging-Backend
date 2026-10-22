"""authors.partner_id stores employee_id or partner_id; drop name/role/employee_id.

Revision ID: 0166_authors_partner_only
Revises: 0165_engagement_feedbacks, 0161_blog_schema
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0166_authors_partner_only"
down_revision = ("0165_engagement_feedbacks", "0161_blog_schema")
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    op.execute(sa.text("ALTER TABLE authors DROP CONSTRAINT IF EXISTS ck_authors_one_owner"))
    op.execute(sa.text("ALTER TABLE authors DROP CONSTRAINT IF EXISTS authors_partner_id_fkey"))

    rows = connection.execute(
        sa.text(
            """
            SELECT a.id, a.employee_id
            FROM authors a
            WHERE a.partner_id IS NULL AND a.employee_id IS NOT NULL
            """
        )
    ).fetchall()
    for author_id, employee_id in rows:
        _assign_partner_id(connection, author_id, employee_id)

    leftover = connection.execute(
        sa.text("SELECT id FROM authors WHERE partner_id IS NULL")
    ).fetchall()
    if leftover:
        raise RuntimeError(
            f"authors rows still missing partner_id: {[row[0] for row in leftover]}"
        )

    op.execute(sa.text("DROP INDEX IF EXISTS ix_authors_employee_id"))
    op.execute(sa.text("ALTER TABLE authors DROP CONSTRAINT IF EXISTS fk_authors_employee_id"))
    op.execute(sa.text("ALTER TABLE authors DROP CONSTRAINT IF EXISTS uq_authors_author_name"))
    op.execute(sa.text("ALTER TABLE authors DROP COLUMN IF EXISTS author_name"))
    op.execute(sa.text("ALTER TABLE authors DROP COLUMN IF EXISTS author_role"))
    op.execute(sa.text("ALTER TABLE authors DROP COLUMN IF EXISTS employee_id"))
    op.alter_column("authors", "partner_id", existing_type=sa.Integer(), nullable=False)
    postgresql.ENUM(name="author_role").drop(op.get_bind(), checkfirst=True)
    op.execute(
        sa.text(
            """
            INSERT INTO authors (partner_id)
            SELECT p.partner_id
            FROM partners p
            WHERE p.role = 'author'
              AND NOT EXISTS (
                  SELECT 1 FROM authors a WHERE a.partner_id = p.partner_id
              )
            """
        )
    )


def _assign_partner_id(connection, author_id: int, employee_id: int) -> None:
    existing = connection.execute(
        sa.text("SELECT id FROM authors WHERE partner_id = :partner_id"),
        {"partner_id": employee_id},
    ).fetchone()
    if existing and existing[0] != author_id:
        connection.execute(
            sa.text("UPDATE posts SET author_id = :keep WHERE author_id = :drop"),
            {"keep": existing[0], "drop": author_id},
        )
        connection.execute(
            sa.text("DELETE FROM authors WHERE id = :author_id"),
            {"author_id": author_id},
        )
        return
    if existing and existing[0] == author_id:
        return
    connection.execute(
        sa.text("UPDATE authors SET partner_id = :partner_id WHERE id = :author_id"),
        {"partner_id": employee_id, "author_id": author_id},
    )


def downgrade() -> None:
    author_role = postgresql.ENUM(
        "nutritionist",
        "doctor",
        "dietitian",
        "fitness_trainer",
        "psychologist",
        "mental_health_expert",
        "health_coach",
        "wellness_expert",
        "researcher",
        "medical_researcher",
        "physiotherapist",
        "yoga_instructor",
        name="author_role",
    )
    author_role.create(op.get_bind(), checkfirst=True)
    op.alter_column("authors", "partner_id", existing_type=sa.Integer(), nullable=True)
    op.add_column("authors", sa.Column("employee_id", sa.Integer(), nullable=True))
    op.add_column(
        "authors",
        sa.Column("author_name", sa.String(length=150), nullable=True),
    )
    op.add_column(
        "authors",
        sa.Column("author_role", postgresql.ENUM(name="author_role", create_type=False), nullable=True),
    )
    op.create_foreign_key(
        "fk_authors_employee_id",
        "authors",
        "employee",
        ["employee_id"],
        ["employee_id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_authors_employee_id", "authors", ["employee_id"], unique=True)
    op.create_unique_constraint("uq_authors_author_name", "authors", ["author_name"])
    op.create_check_constraint(
        "ck_authors_one_owner",
        "authors",
        "(partner_id IS NOT NULL AND employee_id IS NULL) "
        "OR (partner_id IS NULL AND employee_id IS NOT NULL)",
    )
