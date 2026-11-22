"""Normalize staff phones; partners unique on (phone, role).

Revision ID: 0219_partners_phone_role_unique
Revises: 0218_users_dob_provenance

Upgrade:
- Consolidate only the three identity-confirmed phlebo phone-format duplicates
  (approved keep/remove pairs) with reference remaps before uniqueness
- Normalize employee.phone and partners.phone to canonical E.164-style values
- Preflight fail on any remaining collisions the new constraints would reject
- Replace ix_partners_phone with unique (phone, role)

Downgrade:
- Fails safely if any phone appears on more than one partner role
  (old global unique phone index cannot hold multi-role data).
  Never deletes accounts.

Notes:
- Staging already applied 0219 with clean data; amending this file does not
  re-run there (alembic_version stays 0219). Dedup is a no-op when approved
  pairs are absent. Environments that have not yet run 0219 get consolidations
  before the unique index.
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

# Identity-confirmed only. Never auto-merge other (phone, role) collisions.
APPROVED_CONSOLIDATIONS: tuple[dict, ...] = (
    {
        "keep_id": 108,
        "remove_id": 78,
        "role": "phlebo",
        "canonical_phone": "+919307533970",
        "keep_name": "Babasaheb",
        "remove_name": "Babasaheb",
    },
    {
        "keep_id": 49,
        "remove_id": 58,
        "role": "phlebo",
        "canonical_phone": "+919420661939",
        "keep_name": "Madhu Pawar",
        "remove_name": "Madhu Pawar",
    },
    {
        "keep_id": 92,
        "remove_id": 122,
        "role": "phlebo",
        "canonical_phone": "+919971574721",
        "keep_name": "Pramod",
        "remove_name": "Pramod Kumar",
    },
)

_PARTNER_COMPARE_COLS = ("name", "phone", "email", "role", "status")


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


def _table_exists(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _name_matches(actual: str | None, expected: str | None) -> bool:
    if expected is None:
        return True
    left = (actual or "").strip().casefold()
    right = expected.strip().casefold()
    return left == right


def _load_partner(connection, partner_id: int) -> dict | None:
    row = connection.execute(
        text(
            """
            SELECT partner_id, name, phone, email, role::text AS role, status::text AS status
            FROM partners
            WHERE partner_id = :id
            """
        ),
        {"id": partner_id},
    ).mappings().first()
    return dict(row) if row else None


def _field_diffs(keep: dict, remove: dict) -> list[str]:
    diffs: list[str] = []
    for col in _PARTNER_COMPARE_COLS:
        keep_val = keep.get(col)
        remove_val = remove.get(col)
        keep_empty = keep_val is None or str(keep_val).strip() == ""
        remove_empty = remove_val is None or str(remove_val).strip() == ""
        if remove_empty:
            continue
        if keep_empty or str(keep_val).strip() != str(remove_val).strip():
            diffs.append(f"{col}: keep={keep_val!r} remove={remove_val!r}")
    return diffs


def _column_exists(inspector: sa.Inspector, table: str, column: str) -> bool:
    if not _table_exists(inspector, table):
        return False
    return any(col["name"] == column for col in inspector.get_columns(table))


def _reference_counts(connection, partner_id: int) -> dict[str, int]:
    inspector = inspect(connection)
    counts: dict[str, int] = {}
    checks = (
        ("onboarding_assistant_assignment", "partner_id"),
        ("experts", "partner_id"),
        ("partner_auth_otp_sessions", "partner_id"),
        ("partner_auth_tokens", "partner_id"),
        ("authors", "partner_id"),
        ("export_logs", "partner_id"),
        ("camp_consultation_request_otp_contexts", "initiated_by_partner_id"),
    )
    for table, column in checks:
        if not _column_exists(inspector, table, column):
            continue
        n = connection.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE {column} = :id"),
            {"id": partner_id},
        ).scalar()
        counts[f"{table}.{column}"] = int(n or 0)
    return counts


def _resolve_approved_pair(connection, spec: dict) -> tuple[dict, dict] | None:
    """Return (keep_row, remove_row) when an approved pair is present; else None.

    Aborts when rows exist but disagree with the approved identity mapping.
    """
    keep = _load_partner(connection, spec["keep_id"])
    remove = _load_partner(connection, spec["remove_id"])
    canonical = spec["canonical_phone"]
    role = spec["role"]

    if keep is not None and remove is not None:
        keep_phone = _normalize_phone(keep.get("phone"))
        remove_phone = _normalize_phone(remove.get("phone"))
        errors: list[str] = []
        if str(keep.get("role")) != role:
            errors.append(f"keep role={keep.get('role')!r} expected={role!r}")
        if str(remove.get("role")) != role:
            errors.append(f"remove role={remove.get('role')!r} expected={role!r}")
        if keep_phone != canonical:
            errors.append(f"keep phone normalizes to {keep_phone!r}, expected {canonical!r}")
        if remove_phone != canonical:
            errors.append(f"remove phone normalizes to {remove_phone!r}, expected {canonical!r}")
        if not _name_matches(keep.get("name"), spec.get("keep_name")):
            errors.append(
                f"keep name={keep.get('name')!r} expected={spec.get('keep_name')!r}"
            )
        if not _name_matches(remove.get("name"), spec.get("remove_name")):
            errors.append(
                f"remove name={remove.get('name')!r} expected={spec.get('remove_name')!r}"
            )
        if errors:
            raise RuntimeError(
                "Migration 0219 aborted: approved consolidation pair present but "
                f"identity mapping disagrees (keep_id={spec['keep_id']} "
                f"remove_id={spec['remove_id']}): {'; '.join(errors)}. "
                "Confirm identity before merging."
            )
        return keep, remove

    # Fallback: match by normalized phone + role + approved names (other envs).
    rows = connection.execute(
        text(
            """
            SELECT partner_id, name, phone, email, role::text AS role, status::text AS status
            FROM partners
            WHERE role::text = :role
            """
        ),
        {"role": role},
    ).mappings().all()
    candidates = [
        dict(r)
        for r in rows
        if _normalize_phone(r.get("phone")) == canonical
    ]
    if not candidates:
        return None
    if len(candidates) < 2:
        # Single remaining row after prior consolidation — no-op for this pair.
        return None

    # Prefer exact IDs when present among candidates.
    by_id = {int(r["partner_id"]): r for r in candidates}
    if spec["keep_id"] in by_id and spec["remove_id"] in by_id:
        return by_id[spec["keep_id"]], by_id[spec["remove_id"]]

    keep_name = (spec.get("keep_name") or "").strip().casefold()
    remove_name = (spec.get("remove_name") or "").strip().casefold()
    names_distinguishable = keep_name != remove_name and bool(keep_name) and bool(remove_name)

    if names_distinguishable and len(candidates) == 2:
        keep_matches = [
            r for r in candidates if _name_matches(r.get("name"), spec.get("keep_name"))
        ]
        remove_matches = [
            r for r in candidates if _name_matches(r.get("name"), spec.get("remove_name"))
        ]
        if len(keep_matches) == 1 and len(remove_matches) == 1:
            if keep_matches[0]["partner_id"] != remove_matches[0]["partner_id"]:
                return keep_matches[0], remove_matches[0]

    raise RuntimeError(
        "Migration 0219 aborted: phone-role collision matches an approved family "
        f"({canonical!r}/{role}) but partner_ids/names differ from the confirmed "
        f"map keep_id={spec['keep_id']} remove_id={spec['remove_id']}. "
        f"Candidates={[(c['partner_id'], c.get('name'), c.get('phone')) for c in candidates]}. "
        "Confirm identity before merging."
    )


def _remap_onboarding_assignments(
    connection, keep_id: int, remove_id: int
) -> dict[str, int]:
    """Remap or drop OA assignments; abort on metadata conflicts."""
    rows = connection.execute(
        text(
            """
            SELECT onboarding_assistant_id, partner_id, employee_id, engagement_id
            FROM onboarding_assistant_assignment
            WHERE partner_id IN (:keep_id, :remove_id)
            """
        ),
        {"keep_id": keep_id, "remove_id": remove_id},
    ).mappings().all()

    by_engagement: dict[int, dict[str, dict]] = {}
    for row in rows:
        eng = int(row["engagement_id"])
        bucket = by_engagement.setdefault(eng, {})
        key = "keep" if int(row["partner_id"]) == keep_id else "remove"
        bucket[key] = dict(row)

    remapped = 0
    dropped = 0
    for eng, pair in sorted(by_engagement.items()):
        keep_row = pair.get("keep")
        remove_row = pair.get("remove")
        if keep_row and remove_row:
            keep_emp = keep_row.get("employee_id")
            remove_emp = remove_row.get("employee_id")
            if keep_emp != remove_emp:
                raise RuntimeError(
                    "Migration 0219 aborted: onboarding_assistant_assignment conflict "
                    f"on engagement_id={eng}: keep assignment "
                    f"(id={keep_row['onboarding_assistant_id']}, employee_id={keep_emp!r}) "
                    f"vs remove assignment "
                    f"(id={remove_row['onboarding_assistant_id']}, employee_id={remove_emp!r}). "
                    "Preserve both values manually; do not drop."
                )
            connection.execute(
                text(
                    """
                    DELETE FROM onboarding_assistant_assignment
                    WHERE onboarding_assistant_id = :id
                    """
                ),
                {"id": remove_row["onboarding_assistant_id"]},
            )
            dropped += 1
        elif remove_row and not keep_row:
            connection.execute(
                text(
                    """
                    UPDATE onboarding_assistant_assignment
                    SET partner_id = :keep_id
                    WHERE onboarding_assistant_id = :id
                    """
                ),
                {"keep_id": keep_id, "id": remove_row["onboarding_assistant_id"]},
            )
            remapped += 1
    return {"remapped": remapped, "dropped_redundant": dropped}


def _remap_experts(connection, keep_id: int, remove_id: int) -> dict[str, int]:
    inspector = inspect(connection)
    if not _table_exists(inspector, "experts"):
        return {"remapped": 0}
    keep_experts = connection.execute(
        text("SELECT expert_id FROM experts WHERE partner_id = :id"),
        {"id": keep_id},
    ).fetchall()
    remove_experts = connection.execute(
        text("SELECT expert_id FROM experts WHERE partner_id = :id"),
        {"id": remove_id},
    ).fetchall()
    if keep_experts and remove_experts:
        raise RuntimeError(
            "Migration 0219 aborted: both keep and remove partners have experts "
            f"rows (keep_ids={[r[0] for r in keep_experts]}, "
            f"remove_ids={[r[0] for r in remove_experts]}). Resolve manually."
        )
    result = connection.execute(
        text("UPDATE experts SET partner_id = :keep_id WHERE partner_id = :remove_id"),
        {"keep_id": keep_id, "remove_id": remove_id},
    )
    return {"remapped": int(result.rowcount or 0)}


def _remap_authors(connection, keep_id: int, remove_id: int) -> dict[str, int]:
    inspector = inspect(connection)
    if not _table_exists(inspector, "authors"):
        return {"remapped": 0, "deleted_duplicate": 0}
    keep_authors = connection.execute(
        text("SELECT id FROM authors WHERE partner_id = :id"),
        {"id": keep_id},
    ).fetchall()
    remove_authors = connection.execute(
        text("SELECT id FROM authors WHERE partner_id = :id"),
        {"id": remove_id},
    ).fetchall()
    if keep_authors and remove_authors:
        raise RuntimeError(
            "Migration 0219 aborted: both keep and remove partners have authors "
            f"rows (keep={[r[0] for r in keep_authors]}, "
            f"remove={[r[0] for r in remove_authors]}). Resolve manually."
        )
    if remove_authors and not keep_authors:
        result = connection.execute(
            text("UPDATE authors SET partner_id = :keep_id WHERE partner_id = :remove_id"),
            {"keep_id": keep_id, "remove_id": remove_id},
        )
        return {"remapped": int(result.rowcount or 0), "deleted_duplicate": 0}
    return {"remapped": 0, "deleted_duplicate": 0}


def _remap_soft_partner_refs(connection, keep_id: int, remove_id: int) -> dict[str, int]:
    inspector = inspect(connection)
    counts: dict[str, int] = {}
    soft = (
        ("export_logs", "partner_id"),
        ("camp_consultation_request_otp_contexts", "initiated_by_partner_id"),
    )
    for table, column in soft:
        if not _column_exists(inspector, table, column):
            counts[f"{table}.{column}"] = 0
            continue
        result = connection.execute(
            text(f"UPDATE {table} SET {column} = :keep_id WHERE {column} = :remove_id"),
            {"keep_id": keep_id, "remove_id": remove_id},
        )
        counts[f"{table}.{column}"] = int(result.rowcount or 0)
    return counts


def _clear_auth_for_remove(connection, remove_id: int) -> dict[str, int]:
    inspector = inspect(connection)
    counts: dict[str, int] = {}
    for table in ("partner_auth_otp_sessions", "partner_auth_tokens"):
        if not _table_exists(inspector, table):
            counts[table] = 0
            continue
        result = connection.execute(
            text(f"DELETE FROM {table} WHERE partner_id = :id"),
            {"id": remove_id},
        )
        counts[table] = int(result.rowcount or 0)
    return counts


def consolidate_approved_duplicates(connection) -> list[dict]:
    """Run approved-only consolidations. Idempotent when pairs are absent.

    Returns a list of consolidation report dicts (empty when nothing to do).
    """
    reports: list[dict] = []
    for spec in APPROVED_CONSOLIDATIONS:
        resolved = _resolve_approved_pair(connection, spec)
        if resolved is None:
            continue
        keep, remove = resolved
        keep_id = int(keep["partner_id"])
        remove_id = int(remove["partner_id"])
        if keep_id == remove_id:
            continue

        diffs = _field_diffs(keep, remove)
        before_refs = _reference_counts(connection, remove_id)

        oa = _remap_onboarding_assignments(connection, keep_id, remove_id)
        experts = _remap_experts(connection, keep_id, remove_id)
        authors = _remap_authors(connection, keep_id, remove_id)
        soft = _remap_soft_partner_refs(connection, keep_id, remove_id)
        auth = _clear_auth_for_remove(connection, remove_id)

        # Ensure kept phone is canonical before deleting the duplicate.
        connection.execute(
            text("UPDATE partners SET phone = :phone WHERE partner_id = :id"),
            {"phone": spec["canonical_phone"], "id": keep_id},
        )
        connection.execute(
            text("DELETE FROM partners WHERE partner_id = :id"),
            {"id": remove_id},
        )

        report = {
            "keep_id": keep_id,
            "remove_id": remove_id,
            "role": spec["role"],
            "canonical_phone": spec["canonical_phone"],
            "keep_phone": keep.get("phone"),
            "remove_phone": remove.get("phone"),
            "field_diffs": diffs,
            "remove_refs_before": before_refs,
            "oa": oa,
            "experts": experts,
            "authors": authors,
            "soft_refs": soft,
            "auth_cleared": auth,
        }
        reports.append(report)
        print(
            "0219 consolidation: "
            f"keep={keep_id} remove={remove_id} phone={spec['canonical_phone']} "
            f"role={spec['role']} field_diffs={diffs} oa={oa} experts={experts} "
            f"authors={authors} soft={soft} auth={auth}"
        )
    return reports


def _abort_unapproved_phone_role_dupes(connection) -> None:
    partner_rows = connection.execute(
        text("SELECT partner_id, phone, role::text AS role, name FROM partners")
    ).fetchall()
    partner_phone_role: dict[tuple[str, str], list[tuple[int, str | None, str | None]]] = {}
    for partner_id, phone, role, name in partner_rows:
        normalized = _normalize_phone(phone)
        if not normalized:
            continue
        partner_phone_role.setdefault((normalized, str(role)), []).append(
            (int(partner_id), phone, name)
        )

    phone_role_dupes = {k: v for k, v in partner_phone_role.items() if len(v) > 1}
    if not phone_role_dupes:
        return

    details_parts: list[str] = []
    for (p, r), rows in sorted(phone_role_dupes.items()):
        ids = [row[0] for row in rows]
        refs = {pid: _reference_counts(connection, pid) for pid in ids}
        details_parts.append(
            f"phone={p!r} role={r!r} rows={[(pid, ph, nm) for pid, ph, nm in rows]} "
            f"refs={refs}"
        )
    raise RuntimeError(
        "Migration 0219 aborted: duplicate (phone, role) on partners after "
        "approved consolidations. These are NOT auto-merged (identity unconfirmed). "
        f"Resolve manually: {'; '.join(details_parts)}"
    )


def _preflight_and_normalize(connection) -> None:
    partner_rows = connection.execute(
        text("SELECT partner_id, phone, role::text AS role, email FROM partners")
    ).fetchall()
    employee_rows = connection.execute(
        text("SELECT employee_id, phone, email FROM employee")
    ).fetchall()

    partner_updates: list[tuple[str | None, int]] = []
    for partner_id, phone, _role, _email in partner_rows:
        normalized = _normalize_phone(phone)
        partner_updates.append((normalized, partner_id))

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

    reports = consolidate_approved_duplicates(connection)
    if reports:
        print(f"0219: consolidated {len(reports)} approved partner duplicate pair(s)")
    else:
        print("0219: no approved partner duplicate pairs present (consolidator no-op)")

    _abort_unapproved_phone_role_dupes(connection)
    _preflight_and_normalize(connection)

    # Re-check after normalization (defensive).
    _abort_unapproved_phone_role_dupes(connection)

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
