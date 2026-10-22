"""Create blog schema (authors, categories, posts, keywords).

Net schema formerly split across 0161–0167: partner role author, admin
employee authors, post background color/image, focus_keyword as Text.
blog_templates is omitted (create+drop cancelled out).

Renumbered from 0161_blog_schema after merging staging/main onto local
0173_family_onboard_gift_notif so Alembic stays a single linear head.

Revision ID: 0174_blog_schema
Revises: 0173_family_onboard_gift_notif
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0174_blog_schema"
down_revision = "0173_family_onboard_gift_notif"
branch_labels = None
depends_on = None

_AUTHOR_ROLES = (
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
)


def upgrade() -> None:
    connection = op.get_bind()
    # Postgres cannot use a newly added enum label until the ADD VALUE commits.
    # Alembic runs upgrade head in one transaction (env.py); COMMIT here so
    # 0175 can match partners.role = author. Same pattern as 0090 / 0130.
    connection.execute(sa.text("ALTER TYPE partner_role_enum ADD VALUE IF NOT EXISTS 'author'"))
    connection.execute(sa.text("COMMIT"))

    author_role = postgresql.ENUM(*_AUTHOR_ROLES, name="author_role")
    author_role.create(op.get_bind(), checkfirst=True)
    post_status = postgresql.ENUM("draft", "published", name="post_status")
    post_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "authors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("partner_id", sa.Integer(), nullable=True),
        sa.Column("employee_id", sa.Integer(), nullable=True),
        sa.Column("author_name", sa.String(length=150), nullable=False),
        sa.Column("author_role", postgresql.ENUM(name="author_role", create_type=False), nullable=True),
        sa.Column("author_bio", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["partner_id"], ["partners.partner_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employee.employee_id"],
            name="fk_authors_employee_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("partner_id", name="uq_authors_partner_id"),
        sa.UniqueConstraint("author_name", name="uq_authors_author_name"),
        sa.CheckConstraint(
            "(partner_id IS NOT NULL AND employee_id IS NULL) OR (partner_id IS NULL AND employee_id IS NOT NULL)",
            name="ck_authors_one_owner",
        ),
    )
    op.create_index("ix_authors_partner_id", "authors", ["partner_id"], unique=True)
    op.create_index("ix_authors_employee_id", "authors", ["employee_id"], unique=True)

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=150), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_categories_slug"),
    )

    op.create_table(
        "posts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("background_color", sa.String(length=32), nullable=True),
        sa.Column("background_image_url", sa.Text(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="post_status", create_type=False),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["author_id"], ["authors.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("slug", name="uq_posts_slug"),
        sa.CheckConstraint("status IN ('draft', 'published')", name="ck_posts_status"),
    )
    op.create_index("idx_posts_author_id", "posts", ["author_id"])
    op.create_index("idx_posts_category_id", "posts", ["category_id"])
    op.create_index("idx_posts_status", "posts", ["status"])
    op.create_index("idx_posts_created_at", "posts", ["created_at"])

    op.create_table(
        "keywords",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("focus_keyword", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("post_id", name="uq_keywords_post_id"),
    )


def downgrade() -> None:
    op.drop_table("keywords")
    op.drop_index("idx_posts_created_at", table_name="posts")
    op.drop_index("idx_posts_status", table_name="posts")
    op.drop_index("idx_posts_category_id", table_name="posts")
    op.drop_index("idx_posts_author_id", table_name="posts")
    op.drop_table("posts")
    op.drop_table("categories")
    op.drop_index("ix_authors_employee_id", table_name="authors")
    op.drop_index("ix_authors_partner_id", table_name="authors")
    op.drop_table("authors")
    postgresql.ENUM(name="post_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="author_role").drop(op.get_bind(), checkfirst=True)
