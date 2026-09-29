"""Optimize status (smallint) and closed-set columns (PostgreSQL enums).

Revision ID: 0149_column_type_optimization
Revises: 0148_sdb_description, 0148_merge_dx_pkg_addresses
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql


revision = "0149_column_type_optimization"
down_revision = ("0148_sdb_description", "0148_merge_dx_pkg_addresses")
branch_labels = None
depends_on = None


def _table_exists(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _assert_allowed_strings(
    connection: sa.Connection,
    table: str,
    column: str,
    allowed: Sequence[str],
) -> None:
    allowed_set = set(allowed)
    rows = connection.execute(
        text(
            f"""
            SELECT DISTINCT btrim({column}::text) AS v
            FROM {table}
            WHERE {column} IS NOT NULL
            """
        )
    ).fetchall()
    bad = [r[0] for r in rows if r[0] not in allowed_set]
    if bad:
        raise RuntimeError(
            f"Cannot convert {table}.{column}: unexpected values {bad!r}. "
            f"Allowed: {sorted(allowed_set)!r}"
        )


def _status_case_sql(column: str, mapping: dict[str, int]) -> str:
    parts = [f"WHEN btrim({column}::text) = '{label}' THEN {code}" for label, code in mapping.items()]
    return f"CASE {' '.join(parts)} ELSE NULL END"


def _convert_varchar_status(
    connection: sa.Connection,
    table: str,
    column: str,
    mapping: dict[str, int],
    *,
    nullable: bool,
    server_default_code: int | None,
    drop_checks: Sequence[str] = (),
) -> None:
    inspector = inspect(connection)
    if not _table_exists(inspector, table):
        return
    cols = {c["name"] for c in inspector.get_columns(table)}
    if column not in cols:
        return
    _assert_allowed_strings(connection, table, column, list(mapping.keys()))
    for ck in drop_checks:
        op.execute(text(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{ck}"'))
    op.execute(text(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" DROP DEFAULT'))
    case_sql = _status_case_sql(column, mapping)
    op.execute(
        text(
            f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE smallint '
            f"USING ({case_sql})"
        )
    )
    if not nullable:
        op.execute(text(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" SET NOT NULL'))
    if server_default_code is not None:
        op.execute(
            text(
                f'ALTER TABLE "{table}" ALTER COLUMN "{column}" '
                f"SET DEFAULT {server_default_code}"
            )
        )


def _convert_to_enum(
    connection: sa.Connection,
    table: str,
    column: str,
    enum_name: str,
    values: Sequence[str],
    *,
    nullable: bool,
    server_default: str | None,
    drop_checks: Sequence[str] = (),
) -> None:
    inspector = inspect(connection)
    if not _table_exists(inspector, table):
        return
    cols = {c["name"] for c in inspector.get_columns(table)}
    if column not in cols:
        return
    _assert_allowed_strings(connection, table, column, list(values))
    for ck in drop_checks:
        op.execute(text(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{ck}"'))
    op.execute(text(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" DROP DEFAULT'))
    op.execute(
        text(
            f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE {enum_name} '
            f"USING (btrim({column}::text)::{enum_name})"
        )
    )
    if not nullable:
        op.execute(text(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" SET NOT NULL'))
    if server_default is not None:
        op.execute(
            text(
                f'ALTER TABLE "{table}" ALTER COLUMN "{column}" '
                f"SET DEFAULT '{server_default}'::{enum_name}"
            )
        )


def _convert_enum_status_to_smallint(
    connection: sa.Connection,
    table: str,
    column: str,
    mapping: dict[str, int],
    *,
    server_default_code: int,
) -> None:
    inspector = inspect(connection)
    if not _table_exists(inspector, table):
        return
    allowed = list(mapping.keys())
    rows = connection.execute(
        text(
            f"""
            SELECT DISTINCT status::text AS v
            FROM {table}
            WHERE status IS NOT NULL
            """
        )
    ).fetchall()
    bad = [r[0] for r in rows if r[0] not in allowed]
    if bad:
        raise RuntimeError(f"Cannot convert {table}.status: unexpected enum values {bad!r}")
    case_parts = [f"WHEN status::text = '{label}' THEN {code}" for label, code in mapping.items()]
    case_sql = f"CASE {' '.join(case_parts)} ELSE NULL END"
    op.execute(text(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" DROP DEFAULT'))
    op.execute(
        text(
            f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE smallint '
            f"USING ({case_sql})"
        )
    )
    op.execute(text(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" SET NOT NULL'))
    op.execute(
        text(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" SET DEFAULT {server_default_code}')
    )


def upgrade() -> None:
    connection = op.get_bind()

    active_inactive = {"active": 1, "inactive": 2}
    active_inactive_archived = {"active": 1, "inactive": 2, "archived": 3}
    engagement_status = {
        "draft": 1,
        "scheduled": 2,
        "running": 3,
        "completed": 4,
        "cancelled": 5,
        "published": 6,
    }
    integration_sync_status = {"pending": 1, "success": 2, "failed": 3, "skipped": 4}
    notification_status = {"pending": 1, "sent": 2, "failed": 3}
    checklist_task_status = {"pending": 1, "done": 2}
    discount_code_status = {
        "draft": 1,
        "active": 2,
        "paused": 3,
        "expired": 4,
        "finished": 5,
        "disabled": 6,
    }
    discount_instance_status = {"available": 1, "assigned": 2, "used": 3}
    discount_usage_status = {"reserved": 1, "committed": 2, "released": 3}
    override_status = {"available": 1, "unavailable": 2, "booked": 3}
    booking_status = {"pending": 1, "released": 2, "confirmed": 3, "failed": 4}
    order_status = {"created": 1, "paid": 2, "attempted": 3}
    payment_status = {"success": 1, "failed": 2}
    reports_sync_status = {"idle": 1, "in_progress": 2, "failed": 3}
    support_ticket_status = {"open": 1, "resolved": 2, "closed": 3}
    # Prod legacy rows used "complete" on assessment_instances (not category progress).
    assessment_instance_status = {"active": 1, "complete": 2, "completed": 2}
    assessment_progress_status = {"complete": 1, "incomplete": 2}
    blood_booking_status = {"active": 1, "superseded": 2, "cancelled": 3}

    # --- Create PostgreSQL enum types ---
    enum_defs: list[tuple[str, list[str]]] = [
        ("diagnostic_provider_enum", ["healthians", "Healthians"]),
        ("diagnostic_collection_type_enum", ["home_collection", "centre_visit"]),
        ("gender_suitability_enum", ["male", "female", "both"]),
        ("package_for_enum", ["public", "camp"]),
        ("filter_chip_for_enum", ["public_package", "custom_package"]),
        (
            "integration_provider_enum",
            [
                "aurae",
                "n8n",
                "metsights",
                "healthians",
                "bio_ai_reports",
                "nutrition_api",
                "internal",
            ],
        ),
        ("user_gender_enum", ["male", "female", "Male", "Female"]),
        (
            "user_relationship_enum",
            ["self", "spouse", "child", "sibling", "parent", "grandparent", "other"],
        ),
        (
            "diet_preference_enum",
            ["veg", "non_veg", "vegan", "jain", "eggetarian", "keto"],
        ),
        ("partner_role_enum", ["phlebo", "expert", "organization_manager"]),
        ("notification_channel_enum", ["email", "whatsapp"]),
        ("discount_type_enum", ["percentage", "fixed", "percentage_capped"]),
        ("discount_audience_enum", ["everyone", "new_users", "existing_users"]),
        (
            "discount_scope_mode_enum",
            ["general", "organization", "camp", "engagement"],
        ),
        ("discount_package_apply_mode_enum", ["all", "include", "exclude"]),
        ("per_user_frequency_enum", ["none", "day", "week", "month"]),
        ("discount_code_kind_enum", ["shared", "unique_pool"]),
        (
            "discount_scope_type_enum",
            ["general", "organization", "camp", "engagement"],
        ),
        ("discount_package_mode_enum", ["include", "exclude"]),
        (
            "discount_validation_outcome_enum",
            ["ok", "invalid", "ineligible", "locked", "rate_limited"],
        ),
        ("questionnaire_category_of_enum", ["supershyft", "metsights"]),
        ("habit_rule_condition_type_enum", ["option_match", "scale_range"]),
        ("booking_entity_type_enum", ["diagnostic_package"]),
        ("booking_type_enum", ["bio_ai", "blood_test"]),
        ("currency_code_enum", ["INR"]),
        ("export_type_enum", ["participants", "database_backup"]),
        ("export_format_enum", ["csv", "xlsx"]),
        (
            "export_source_kind_enum",
            ["engagement", "organization", "camp", "system"],
        ),
        ("checklist_audience_enum", ["internal", "user"]),
    ]
    for enum_name, values in enum_defs:
        pg_enum = postgresql.ENUM(*values, name=enum_name, create_type=False)
        pg_enum.create(connection, checkfirst=True)

    # Notifications partial index uses string status; drop and recreate after conversion.
    op.execute(text("DROP INDEX IF EXISTS ix_notifications_pending_dispatched_at"))

    # --- Status columns ---
    _convert_varchar_status(
        connection,
        "diagnostic_package",
        "status",
        active_inactive,
        nullable=True,
        server_default_code=1,
        drop_checks=("ck_diagnostic_package_status_allowed",),
    )
    _convert_varchar_status(
        connection,
        "diagnostic_package_filters_chips",
        "status",
        active_inactive,
        nullable=True,
        server_default_code=1,
    )
    _convert_varchar_status(
        connection,
        "experts",
        "status",
        active_inactive,
        nullable=False,
        server_default_code=1,
    )
    _convert_varchar_status(
        connection,
        "questionnaire_healthy_habit_rules",
        "status",
        active_inactive,
        nullable=False,
        server_default_code=1,
    )
    for tbl in (
        "users",
        "organizations",
        "employee",
        "partners",
        "assessment_packages",
        "questionnaire_definitions",
        "questionnaire_categories",
        "checklist_templates",
    ):
        default_code = 1
        _convert_varchar_status(
            connection,
            tbl,
            "status",
            active_inactive_archived,
            nullable=tbl != "organizations",
            server_default_code=default_code if tbl in ("partners", "checklist_templates", "questionnaire_categories") else None,
        )
    _convert_varchar_status(
        connection,
        "engagements",
        "status",
        engagement_status,
        nullable=True,
        server_default_code=None,
    )
    _convert_varchar_status(
        connection,
        "integration_sync_logs",
        "status",
        integration_sync_status,
        nullable=True,
        server_default_code=None,
    )
    op.execute(text('ALTER TABLE notifications DROP CONSTRAINT IF EXISTS "ck_notifications_status"'))
    _convert_varchar_status(
        connection,
        "notifications",
        "status",
        notification_status,
        nullable=False,
        server_default_code=None,
    )
    _convert_varchar_status(
        connection,
        "engagement_checklist_tasks",
        "status",
        checklist_task_status,
        nullable=False,
        server_default_code=1,
    )
    _convert_varchar_status(
        connection,
        "discount_codes",
        "status",
        discount_code_status,
        nullable=False,
        server_default_code=1,
    )
    _convert_varchar_status(
        connection,
        "discount_code_instances",
        "status",
        discount_instance_status,
        nullable=False,
        server_default_code=1,
    )
    _convert_varchar_status(
        connection,
        "discount_usages",
        "status",
        discount_usage_status,
        nullable=False,
        server_default_code=1,
    )
    _convert_varchar_status(
        connection,
        "expert_availability_overrides",
        "status",
        override_status,
        nullable=False,
        server_default_code=None,
    )
    _convert_varchar_status(
        connection,
        "bookings",
        "status",
        booking_status,
        nullable=False,
        server_default_code=1,
    )
    _convert_varchar_status(
        connection,
        "orders",
        "status",
        order_status,
        nullable=False,
        server_default_code=1,
    )
    _convert_varchar_status(
        connection,
        "payments",
        "status",
        payment_status,
        nullable=False,
        server_default_code=None,
    )
    _convert_varchar_status(
        connection,
        "reports_user_sync_state",
        "sync_status",
        reports_sync_status,
        nullable=False,
        server_default_code=1,
    )
    _convert_varchar_status(
        connection,
        "support_tickets",
        "status",
        support_ticket_status,
        nullable=False,
        server_default_code=1,
    )
    _convert_varchar_status(
        connection,
        "assessment_instances",
        "status",
        assessment_instance_status,
        nullable=True,
        server_default_code=None,
    )
    _convert_varchar_status(
        connection,
        "assessment_category_progress",
        "status",
        assessment_progress_status,
        nullable=False,
        server_default_code=None,
    )

    if _table_exists(inspect(connection), "participant_blood_bookings"):
        _convert_enum_status_to_smallint(
            connection,
            "participant_blood_bookings",
            "status",
            blood_booking_status,
            server_default_code=1,
        )
        op.execute(text("DROP TYPE IF EXISTS blood_booking_status_enum"))

    op.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_notifications_pending_dispatched_at
            ON notifications (dispatched_at)
            WHERE status = 1 AND dispatched_at IS NOT NULL
            """
        )
    )

    # --- Enum columns: diagnostics ---
    _convert_to_enum(
        connection,
        "diagnostic_package",
        "diagnostic_provider",
        "diagnostic_provider_enum",
        ["healthians", "Healthians"],
        nullable=True,
        server_default=None,
    )
    _convert_to_enum(
        connection,
        "diagnostic_package",
        "collection_type",
        "diagnostic_collection_type_enum",
        ["home_collection", "centre_visit"],
        nullable=True,
        server_default=None,
        drop_checks=("ck_diagnostic_package_collection_type_allowed",),
    )
    _convert_to_enum(
        connection,
        "diagnostic_package",
        "gender_suitability",
        "gender_suitability_enum",
        ["male", "female", "both"],
        nullable=True,
        server_default=None,
        drop_checks=("ck_diagnostic_package_gender_allowed",),
    )
    _convert_to_enum(
        connection,
        "diagnostic_package",
        "package_for",
        "package_for_enum",
        ["public", "camp"],
        nullable=False,
        server_default="public",
    )
    _convert_to_enum(
        connection,
        "diagnostic_package_filters_chips",
        "chip_for",
        "filter_chip_for_enum",
        ["public_package", "custom_package"],
        nullable=False,
        server_default="public_package",
        drop_checks=("ck_diagnostic_filters_chips_chip_for_allowed",),
    )
    for tbl in ("diagnostic_test_groups", "health_parameters"):
        _convert_to_enum(
            connection,
            tbl,
            "gender_suitability",
            "gender_suitability_enum",
            ["male", "female", "both"],
            nullable=True,
            server_default=None,
            drop_checks=(
                "ck_diagnostic_test_groups_gender_allowed",
                "ck_health_parameters_diag_gender_allowed",
            ),
        )
    _convert_to_enum(
        connection,
        "diagnostic_test_groups",
        "package_for",
        "package_for_enum",
        ["public", "camp"],
        nullable=False,
        server_default="public",
    )

    _convert_to_enum(
        connection,
        "integration_sync_logs",
        "provider",
        "integration_provider_enum",
        [
            "aurae",
            "n8n",
            "metsights",
            "healthians",
            "bio_ai_reports",
            "nutrition_api",
            "internal",
        ],
        nullable=False,
        server_default=None,
    )

    _convert_to_enum(
        connection,
        "users",
        "gender",
        "user_gender_enum",
        ["male", "female", "Male", "Female"],
        nullable=True,
        server_default=None,
    )
    _convert_to_enum(
        connection,
        "users",
        "relationship",
        "user_relationship_enum",
        ["self", "spouse", "child", "sibling", "parent", "grandparent", "other"],
        nullable=False,
        server_default="self",
    )
    _convert_to_enum(
        connection,
        "user_preferences",
        "diet_preference",
        "diet_preference_enum",
        ["veg", "non_veg", "vegan", "jain", "eggetarian", "keto"],
        nullable=True,
        server_default=None,
    )
    _convert_to_enum(
        connection,
        "partners",
        "role",
        "partner_role_enum",
        ["phlebo", "expert", "organization_manager"],
        nullable=False,
        server_default=None,
        drop_checks=("ck_partners_role",),
    )
    _convert_to_enum(
        connection,
        "notification_services",
        "channel",
        "notification_channel_enum",
        ["email", "whatsapp"],
        nullable=False,
        server_default=None,
        drop_checks=("ck_notification_services_channel",),
    )
    _convert_to_enum(
        connection,
        "notifications",
        "channel",
        "notification_channel_enum",
        ["email", "whatsapp"],
        nullable=False,
        server_default=None,
        drop_checks=("ck_notifications_channel",),
    )

    # Discounts
    _convert_to_enum(
        connection,
        "discount_codes",
        "discount_type",
        "discount_type_enum",
        ["percentage", "fixed", "percentage_capped"],
        nullable=False,
        server_default=None,
    )
    _convert_to_enum(
        connection,
        "discount_codes",
        "audience",
        "discount_audience_enum",
        ["everyone", "new_users", "existing_users"],
        nullable=False,
        server_default="everyone",
    )
    _convert_to_enum(
        connection,
        "discount_codes",
        "scope_mode",
        "discount_scope_mode_enum",
        ["general", "organization", "camp", "engagement"],
        nullable=False,
        server_default="general",
    )
    _convert_to_enum(
        connection,
        "discount_codes",
        "package_apply_mode",
        "discount_package_apply_mode_enum",
        ["all", "include", "exclude"],
        nullable=False,
        server_default="all",
    )
    _convert_to_enum(
        connection,
        "discount_codes",
        "per_user_frequency",
        "per_user_frequency_enum",
        ["none", "day", "week", "month"],
        nullable=False,
        server_default="none",
    )
    _convert_to_enum(
        connection,
        "discount_codes",
        "code_kind",
        "discount_code_kind_enum",
        ["shared", "unique_pool"],
        nullable=False,
        server_default="shared",
    )
    _convert_to_enum(
        connection,
        "discount_code_scopes",
        "scope_type",
        "discount_scope_type_enum",
        ["general", "organization", "camp", "engagement"],
        nullable=False,
        server_default=None,
    )
    _convert_to_enum(
        connection,
        "discount_code_packages",
        "mode",
        "discount_package_mode_enum",
        ["include", "exclude"],
        nullable=False,
        server_default=None,
    )
    _convert_to_enum(
        connection,
        "discount_validation_attempts",
        "outcome",
        "discount_validation_outcome_enum",
        ["ok", "invalid", "ineligible", "locked", "rate_limited"],
        nullable=False,
        server_default=None,
    )

    _convert_to_enum(
        connection,
        "questionnaire_categories",
        "category_of",
        "questionnaire_category_of_enum",
        ["supershyft", "metsights"],
        nullable=False,
        server_default="supershyft",
    )
    _convert_to_enum(
        connection,
        "questionnaire_healthy_habit_rules",
        "condition_type",
        "habit_rule_condition_type_enum",
        ["option_match", "scale_range"],
        nullable=False,
        server_default=None,
    )

    _convert_to_enum(
        connection,
        "bookings",
        "entity_type",
        "booking_entity_type_enum",
        ["diagnostic_package"],
        nullable=False,
        server_default=None,
    )
    _convert_to_enum(
        connection,
        "bookings",
        "booking_type",
        "booking_type_enum",
        ["bio_ai", "blood_test"],
        nullable=True,
        server_default=None,
    )
    _convert_to_enum(
        connection,
        "bookings",
        "currency",
        "currency_code_enum",
        ["INR"],
        nullable=False,
        server_default="INR",
    )
    for tbl in ("orders", "payments"):
        _convert_to_enum(
            connection,
            tbl,
            "currency",
            "currency_code_enum",
            ["INR"],
            nullable=False,
            server_default="INR",
        )

    _convert_to_enum(
        connection,
        "export_logs",
        "export_type",
        "export_type_enum",
        ["participants", "database_backup"],
        nullable=False,
        server_default=None,
    )
    _convert_to_enum(
        connection,
        "export_logs",
        "export_format",
        "export_format_enum",
        ["csv", "xlsx"],
        nullable=False,
        server_default=None,
    )
    _convert_to_enum(
        connection,
        "export_logs",
        "source_kind",
        "export_source_kind_enum",
        ["engagement", "organization", "camp", "system"],
        nullable=False,
        server_default=None,
    )
    _convert_to_enum(
        connection,
        "checklist_templates",
        "audience",
        "checklist_audience_enum",
        ["internal", "user"],
        nullable=False,
        server_default="internal",
        drop_checks=("ck_checklist_templates_audience",),
    )

    # discount_usages.camp_no -> bigint when all numeric
    inspector = inspect(connection)
    if _table_exists(inspector, "discount_usages"):
        bad = connection.execute(
            text(
                """
                SELECT DISTINCT camp_no FROM discount_usages
                WHERE camp_no IS NOT NULL AND camp_no !~ '^[0-9]+$'
                """
            )
        ).fetchall()
        if bad:
            raise RuntimeError(
                f"Cannot convert discount_usages.camp_no to bigint: non-numeric values {bad!r}"
            )
        op.execute(
            text(
                """
                ALTER TABLE discount_usages
                ALTER COLUMN camp_no TYPE bigint
                USING CASE WHEN camp_no IS NULL THEN NULL ELSE camp_no::bigint END
                """
            )
        )


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
