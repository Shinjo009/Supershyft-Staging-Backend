"""Discount module tables + diagnostic_package.min_price + discounts RBAC category.

Revision ID: 0137_discount_module
Revises: 0136_org_manager_partners
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "0137_discount_module"
down_revision = "0136_org_manager_partners"
branch_labels = None
depends_on = None


def _table_exists(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_exists(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    if not _table_exists(inspector, table_name):
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _index_exists(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    if not _table_exists(inspector, table_name):
        return False
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def _create_index_if_missing(
    inspector: sa.Inspector,
    index_name: str,
    table_name: str,
    columns: list[str],
) -> None:
    if _index_exists(inspector, table_name, index_name):
        return
    op.create_index(index_name, table_name, columns)


def _migrate_user_audit_column_to_employee(
    conn,
    inspector: sa.Inspector,
    table: str,
    old_col: str,
    new_col: str,
) -> None:
    if not _table_exists(inspector, table):
        return
    if _column_exists(inspector, table, new_col):
        return
    if not _column_exists(inspector, table, old_col):
        op.add_column(
            table,
            sa.Column(
                new_col,
                sa.Integer(),
                sa.ForeignKey("employee.employee_id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        return

    conn.execute(
        sa.text(
            f"""
            ALTER TABLE {table}
            DROP CONSTRAINT IF EXISTS {table}_{old_col}_fkey
            """
        )
    )
    conn.execute(sa.text(f"ALTER TABLE {table} RENAME COLUMN {old_col} TO {new_col}"))
    conn.execute(
        sa.text(
            f"""
            ALTER TABLE {table}
            ADD CONSTRAINT {table}_{new_col}_fkey
            FOREIGN KEY ({new_col}) REFERENCES employee (employee_id) ON DELETE SET NULL
            """
        )
    )


def _create_discount_tables(inspector: sa.Inspector) -> None:
    if _table_exists(inspector, "discount_codes"):
        return

    op.create_table(
        "discount_codes",
        sa.Column("discount_code_id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("discount_type", sa.String(32), nullable=False),
        sa.Column("percent_value", sa.Numeric(5, 2), nullable=True),
        sa.Column("fixed_amount_paise", sa.Integer(), nullable=True),
        sa.Column("max_discount_paise", sa.Integer(), nullable=True),
        sa.Column("hard_ceiling_paise", sa.Integer(), nullable=True),
        sa.Column("min_bill_paise", sa.Integer(), nullable=True),
        sa.Column("combine_with_others", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("auto_apply", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("audience", sa.String(32), nullable=False, server_default="everyone"),
        sa.Column("first_purchase_only", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("scope_mode", sa.String(32), nullable=False, server_default="general"),
        sa.Column("package_apply_mode", sa.String(32), nullable=False, server_default="all"),
        sa.Column("include_addons", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_of_day_start", sa.String(8), nullable=True),
        sa.Column("time_of_day_end", sa.String(8), nullable=True),
        sa.Column("days_of_week", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("camp_valid_days_after", sa.Integer(), nullable=True),
        sa.Column("max_total_uses", sa.Integer(), nullable=True),
        sa.Column("max_uses_per_user", sa.Integer(), nullable=True),
        sa.Column("per_user_frequency", sa.String(16), nullable=False, server_default="none"),
        sa.Column("max_uses_per_camp", sa.Integer(), nullable=True),
        sa.Column("max_uses_per_order", sa.Integer(), nullable=True),
        sa.Column("max_total_discount_paise", sa.Integer(), nullable=True),
        sa.Column("total_discount_given_paise", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("code_kind", sa.String(32), nullable=False, server_default="shared"),
        sa.Column(
            "referral_user_id",
            sa.Integer(),
            sa.ForeignKey("users.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("min_price_protection", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_employee_id",
            sa.Integer(),
            sa.ForeignKey("employee.employee_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_employee_id",
            sa.Integer(),
            sa.ForeignKey("employee.employee_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("code", name="uq_discount_codes_code"),
    )

    op.create_table(
        "discount_code_scopes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "discount_code_id",
            sa.Integer(),
            sa.ForeignKey("discount_codes.discount_code_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope_type", sa.String(32), nullable=False),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "discount_code_id",
            "scope_type",
            "scope_key",
            name="uq_discount_code_scopes",
        ),
    )

    op.create_table(
        "discount_code_packages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "discount_code_id",
            sa.Integer(),
            sa.ForeignKey("discount_codes.discount_code_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "diagnostic_package_id",
            sa.Integer(),
            sa.ForeignKey("diagnostic_package.diagnostic_package_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.UniqueConstraint(
            "discount_code_id",
            "diagnostic_package_id",
            "mode",
            name="uq_discount_code_packages",
        ),
    )

    op.create_table(
        "discount_code_cities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "discount_code_id",
            sa.Integer(),
            sa.ForeignKey("discount_codes.discount_code_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("city", sa.String(128), nullable=False),
        sa.UniqueConstraint("discount_code_id", "city", name="uq_discount_code_cities"),
    )

    op.create_table(
        "discount_allowlist_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "discount_code_id",
            sa.Integer(),
            sa.ForeignKey("discount_codes.discount_code_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "discount_code_instances",
        sa.Column("instance_id", sa.Integer(), primary_key=True),
        sa.Column(
            "discount_code_id",
            sa.Integer(),
            sa.ForeignKey("discount_codes.discount_code_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column(
            "assigned_user_id",
            sa.Integer(),
            sa.ForeignKey("users.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="available"),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("code", name="uq_discount_code_instances_code"),
    )

    op.create_table(
        "discount_usages",
        sa.Column("usage_id", sa.Integer(), primary_key=True),
        sa.Column(
            "discount_code_id",
            sa.Integer(),
            sa.ForeignKey("discount_codes.discount_code_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "instance_id",
            sa.Integer(),
            sa.ForeignKey("discount_code_instances.instance_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.order_id", ondelete="SET NULL"), nullable=True),
        sa.Column("booking_ids", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("original_paise", sa.Integer(), nullable=False),
        sa.Column("discount_paise", sa.Integer(), nullable=False),
        sa.Column("final_paise", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("camp_no", sa.String(64), nullable=True),
        sa.Column("engagement_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="reserved"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "discount_code_audit",
        sa.Column("audit_id", sa.Integer(), primary_key=True),
        sa.Column(
            "discount_code_id",
            sa.Integer(),
            sa.ForeignKey("discount_codes.discount_code_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_employee_id",
            sa.Integer(),
            sa.ForeignKey("employee.employee_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("diff", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "discount_validation_attempts",
        sa.Column("attempt_id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("client_ip", sa.String(64), nullable=True),
        sa.Column("code_submitted", sa.String(64), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("endpoint", sa.String(128), nullable=True),
        sa.Column("detail", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def _ensure_discount_indexes(inspector: sa.Inspector) -> None:
    _create_index_if_missing(inspector, "ix_discount_codes_status", "discount_codes", ["status"])
    _create_index_if_missing(inspector, "ix_discount_codes_scope_mode", "discount_codes", ["scope_mode"])
    _create_index_if_missing(inspector, "ix_discount_codes_auto_apply", "discount_codes", ["auto_apply"])
    _create_index_if_missing(
        inspector, "ix_discount_code_scopes_lookup", "discount_code_scopes", ["scope_type", "scope_key"]
    )
    _create_index_if_missing(
        inspector, "ix_discount_allowlist_phone", "discount_allowlist_users", ["discount_code_id", "phone"]
    )
    _create_index_if_missing(
        inspector, "ix_discount_allowlist_email", "discount_allowlist_users", ["discount_code_id", "email"]
    )
    _create_index_if_missing(
        inspector, "ix_discount_instances_parent", "discount_code_instances", ["discount_code_id", "status"]
    )
    _create_index_if_missing(
        inspector, "ix_discount_usages_code_status", "discount_usages", ["discount_code_id", "status"]
    )
    _create_index_if_missing(
        inspector, "ix_discount_usages_user_code", "discount_usages", ["user_id", "discount_code_id", "status"]
    )
    _create_index_if_missing(inspector, "ix_discount_usages_order", "discount_usages", ["order_id"])
    _create_index_if_missing(
        inspector, "ix_discount_code_audit_code", "discount_code_audit", ["discount_code_id", "created_at"]
    )
    _create_index_if_missing(
        inspector, "ix_discount_attempts_user_created", "discount_validation_attempts", ["user_id", "created_at"]
    )
    _create_index_if_missing(
        inspector, "ix_discount_attempts_ip_created", "discount_validation_attempts", ["client_ip", "created_at"]
    )


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    op.execute(sa.text("SET LOCAL lock_timeout = '15s'"))
    op.execute(
        sa.text(
            "ALTER TABLE diagnostic_package "
            "ADD COLUMN IF NOT EXISTS min_price NUMERIC(10, 2)"
        )
    )

    _create_discount_tables(inspector)
    inspector = inspect(conn)

    _migrate_user_audit_column_to_employee(
        conn, inspector, "discount_codes", "created_by", "created_employee_id"
    )
    _migrate_user_audit_column_to_employee(
        conn, inspector, "discount_codes", "updated_by", "updated_employee_id"
    )
    inspector = inspect(conn)
    _migrate_user_audit_column_to_employee(
        conn, inspector, "discount_code_audit", "actor_user_id", "actor_employee_id"
    )

    inspector = inspect(conn)
    _ensure_discount_indexes(inspector)

    conn.execute(
        sa.text(
            """
            INSERT INTO permission_categories (category_key, display_name, description, display_order, is_active)
            VALUES (
              'discounts',
              'Discounts',
              'Discount codes, instances, allowlists, and reports',
              (SELECT COALESCE(MAX(display_order), 0) + 1 FROM permission_categories),
              true
            )
            ON CONFLICT (category_key) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported for 0137_discount_module")
