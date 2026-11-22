"""Normalize staff phones; partners unique on (phone, role).

Revision ID: 0219_partners_phone_role_unique
Revises: 0218_users_dob_provenance

Upgrade:
- Normalize employee.phone and partners.phone to canonical E.164-style values
- Preflight fail on collisions the new constraints would reject
- Replace ix_partners_phone with unique (phone, role)

Downgrade:
- Fails safely if any phone appears on more than one partner role
  (old global unique phone index cannot hold multi-role data).
  Never deletes accounts.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision = "0219_partners_phone_role_unique"
down_revision = "0218_users_dob_provenance"
branch_labels = None
depends_on = None

_MIN_DIGITS = 8
_ALLOWED = frozenset("0123456789+ -()")


def _normalize_phone(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    if any(ch not in _ALLOWED for ch in value):
        return value.strip() or None
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < _MIN_DIGITS:
        return value.strip() or None
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+91{digits[2:]}"
    if len(digits) == 11 and digits.startswith("0"):
        return f"+91{digits[1:]}"
    return f"+{digits}"


def _index_exists(inspector: sa.Inspector, table: str, name: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return any(idx["name"] == name for idx in inspector.get_indexes(table))


def _preflight_and_normalize(connection) -> None:
    partner_rows = connection.execute(
        text("SELECT partner_id, phone, role, email FROM partners")
    ).fetchall()
    employee_rows = connection.execute(
        text("SELECT employee_id, phone, email FROM employee")
    ).fetchall()

    # Normalize phones in memory then check collisions before writing.
    partner_updates: list[tuple[str | None, int]] = []
    partner_phone_role: dict[tuple[str, str], list[int]] = {}
    for partner_id, phone, role, _email in partner_rows:
        normalized = _normalize_phone(phone)
        partner_updates.append((normalized, partner_id))
        if normalized:
            partner_phone_role.setdefault((normalized, str(role)), []).append(partner_id)

    phone_role_dupes = {k: v for k, v in partner_phone_role.items() if len(v) > 1}
    if phone_role_dupes:
        details = "; ".join(
            f"phone={p!r} role={r!r} partner_ids={ids}"
            for (p, r), ids in sorted(phone_role_dupes.items())
        )
        raise RuntimeError(
            "Migration 0219 aborted: duplicate (phone, role) on partners after "
            f"normalization. Resolve manually (never merge/delete silently): {details}"
        )

    employee_updates: list[tuple[str | None, int]] = []
    employee_phones: dict[str, list[int]] = {}
    employee_emails: dict[str, list[int]] = {}
    for employee_id, phone, email in employee_rows:
        normalized = _normalize_phone(phone)
        employee_updates.append((normalized, employee_id))
        if normalized:
            employee_phones.setdefault(normalized, []).append(employee_id)
        if email and str(email).strip():
            key = str(email).strip().lower()
            employee_emails.setdefault(key, []).append(employee_id)

    emp_phone_dupes = {k: v for k, v in employee_phones.items() if len(v) > 1}
    if emp_phone_dupes:
        details = "; ".join(
            f"phone={p!r} employee_ids={ids}" for p, ids in sorted(emp_phone_dupes.items())
        )
        raise RuntimeError(
            "Migration 0219 aborted: duplicate employee phones after normalization: "
            f"{details}"
        )

    emp_email_dupes = {k: v for k, v in employee_emails.items() if len(v) > 1}
    if emp_email_dupes:
        details = "; ".join(
            f"email={e!r} employee_ids={ids}" for e, ids in sorted(emp_email_dupes.items())
        )
        raise RuntimeError(
            "Migration 0219 aborted: duplicate employee emails (case-insensitive): "
            f"{details}"
        )

    partner_emails: dict[str, list[int]] = {}
    for partner_id, _phone, _role, email in partner_rows:
        if email and str(email).strip():
            key = str(email).strip().lower()
            partner_emails.setdefault(key, []).append(partner_id)
    partner_email_dupes = {k: v for k, v in partner_emails.items() if len(v) > 1}
    if partner_email_dupes:
        details = "; ".join(
            f"email={e!r} partner_ids={ids}" for e, ids in sorted(partner_email_dupes.items())
        )
        raise RuntimeError(
            "Migration 0219 aborted: duplicate partner emails under global unique "
            f"constraint: {details}"
        )

    for normalized, partner_id in partner_updates:
        connection.execute(
            text("UPDATE partners SET phone = :phone WHERE partner_id = :id"),
            {"phone": normalized, "id": partner_id},
        )
    for normalized, employee_id in employee_updates:
        connection.execute(
            text("UPDATE employee SET phone = :phone WHERE employee_id = :id"),
            {"phone": normalized, "id": employee_id},
        )


def upgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)

    _preflight_and_normalize(connection)

    if _index_exists(inspector, "partners", "ix_partners_phone"):
        op.drop_index("ix_partners_phone", table_name="partners")

    inspector = inspect(connection)
    if not _index_exists(inspector, "partners", "ix_partners_phone_role"):
        op.create_index(
            "ix_partners_phone_role",
            "partners",
            ["phone", "role"],
            unique=True,
        )


def downgrade() -> None:
    connection = op.get_bind()
    multi = connection.execute(
        text(
            """
            SELECT phone, array_agg(partner_id ORDER BY partner_id) AS partner_ids, COUNT(*) AS n
            FROM partners
            WHERE phone IS NOT NULL AND btrim(phone) <> ''
            GROUP BY phone
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    if multi:
        details = "; ".join(
            f"phone={row[0]!r} partner_ids={list(row[1])} count={row[2]}"
            for row in multi
        )
        raise RuntimeError(
            "Downgrade of 0219 aborted: multiple partner roles share the same phone "
            "under the new rules, so the old global unique phone index cannot be "
            "restored without deleting or rewriting accounts (not allowed). "
            "Manual recovery: keep only one partners row per phone (or change phones) "
            f"then retry downgrade. Conflicts: {details}"
        )

    inspector = inspect(connection)
    if _index_exists(inspector, "partners", "ix_partners_phone_role"):
        op.drop_index("ix_partners_phone_role", table_name="partners")
    if not _index_exists(inspector, "partners", "ix_partners_phone"):
        op.create_index("ix_partners_phone", "partners", ["phone"], unique=True)
