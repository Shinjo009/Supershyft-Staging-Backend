"""Fixture tests for approved-only partner dedup in migration 0219."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "db"
    / "migrations"
    / "versions"
    / "0219_partners_phone_role_unique.py"
)
_spec = importlib.util.spec_from_file_location(
    "migration_0219_partners_phone_role_unique", _MIGRATION_PATH
)
assert _spec is not None and _spec.loader is not None
migration_0219 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration_0219)


@pytest.fixture
async def drop_partners_phone_role_unique(test_db_session):
    """Allow seeding same-role phone-format duplicates for consolidator tests."""
    await test_db_session.execute(text("DROP INDEX IF EXISTS ix_partners_phone_role"))
    await test_db_session.commit()
    yield
    await test_db_session.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ix_partners_phone_role
            ON partners (phone, role)
            """
        )
    )
    await test_db_session.commit()


def _run_consolidate(sync_conn):
    return migration_0219.consolidate_approved_duplicates(sync_conn)


async def _insert_partner(
    session,
    *,
    partner_id: int,
    name: str,
    phone: str,
    role: str = "phlebo",
    email: str | None = None,
    status: int = 1,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO partners (partner_id, name, phone, email, role, status)
            VALUES (
                :id, :name, :phone, :email,
                CAST(:role AS partner_role_enum),
                :status
            )
            """
        ),
        {
            "id": partner_id,
            "name": name,
            "phone": phone,
            "email": email or f"p{partner_id}@example.com",
            "role": role,
            "status": status,
        },
    )


async def _insert_oa(session, *, oa_id: int, partner_id: int, engagement_id: int) -> None:
    await session.execute(
        text(
            """
            INSERT INTO onboarding_assistant_assignment
                (onboarding_assistant_id, partner_id, employee_id, engagement_id)
            VALUES (:oa_id, :partner_id, NULL, :engagement_id)
            """
        ),
        {"oa_id": oa_id, "partner_id": partner_id, "engagement_id": engagement_id},
    )


async def _ensure_engagement(session, engagement_id: int) -> None:
    existing = await session.execute(
        text("SELECT 1 FROM engagements WHERE engagement_id = :id"),
        {"id": engagement_id},
    )
    if existing.scalar() is not None:
        return
    # Minimal engagement row — reuse packages if present, else skip FK-heavy setup
    # by inserting only when diagnostic/assessment packages exist.
    pkg = await session.execute(text("SELECT diagnostic_package_id FROM diagnostic_package LIMIT 1"))
    diag_id = pkg.scalar()
    apkg = await session.execute(text("SELECT package_id FROM assessment_packages LIMIT 1"))
    assess_id = apkg.scalar()
    etype = await session.execute(text("SELECT id FROM engagement_types LIMIT 1"))
    type_id = etype.scalar()
    if diag_id is None or assess_id is None or type_id is None:
        pytest.skip("engagement FK seed data missing")
    await session.execute(
        text(
            """
            INSERT INTO engagements (
                engagement_id, engagement_name, engagement_code, engagement_type,
                assessment_package_id, diagnostic_package_id, status, start_date, end_date
            ) VALUES (
                :id, 'Dedup Test', :code, :type_id, :assess_id, :diag_id,
                3, CURRENT_DATE, CURRENT_DATE
            )
            """
        ),
        {
            "id": engagement_id,
            "code": f"DEDUP{engagement_id}",
            "type_id": type_id,
            "assess_id": assess_id,
            "diag_id": diag_id,
        },
    )


@pytest.mark.asyncio
async def test_consolidate_approved_phone_format_pair(
    test_db_session, test_engine, drop_partners_phone_role_unique
):
    await _insert_partner(
        test_db_session,
        partner_id=108,
        name="Babasaheb",
        phone="9307533970",
    )
    await _insert_partner(
        test_db_session,
        partner_id=78,
        name="Babasaheb",
        phone="93075 33970",
    )
    await test_db_session.commit()

    def _run(sync_conn):
        return _run_consolidate(sync_conn)

    async with test_engine.begin() as conn:
        reports = await conn.run_sync(_run)

    assert len(reports) == 1
    assert reports[0]["keep_id"] == 108
    assert reports[0]["remove_id"] == 78

    remaining = await test_db_session.execute(
        text("SELECT partner_id, phone FROM partners WHERE partner_id IN (108, 78) ORDER BY partner_id")
    )
    rows = remaining.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 108
    assert rows[0][1] == "+919307533970"


@pytest.mark.asyncio
async def test_consolidate_same_engagement_drops_redundant_assignment(
    test_db_session, test_engine, drop_partners_phone_role_unique
):
    await _ensure_engagement(test_db_session, 91024)
    await _insert_partner(
        test_db_session, partner_id=49, name="Madhu Pawar", phone="9420661939"
    )
    await _insert_partner(
        test_db_session, partner_id=58, name="Madhu Pawar", phone="94206 61939"
    )
    await _insert_oa(test_db_session, oa_id=91001, partner_id=49, engagement_id=91024)
    await _insert_oa(test_db_session, oa_id=91002, partner_id=58, engagement_id=91024)
    await test_db_session.commit()

    async with test_engine.begin() as conn:
        reports = await conn.run_sync(_run_consolidate)

    assert reports[0]["oa"]["dropped_redundant"] == 1
    assert reports[0]["oa"]["remapped"] == 0

    oa_rows = await test_db_session.execute(
        text(
            """
            SELECT onboarding_assistant_id, partner_id
            FROM onboarding_assistant_assignment
            WHERE engagement_id = 91024
            """
        )
    )
    rows = oa_rows.fetchall()
    assert len(rows) == 1
    assert rows[0][1] == 49


@pytest.mark.asyncio
async def test_consolidate_assignment_metadata_conflict_aborts(
    test_db_session, test_engine, drop_partners_phone_role_unique
):
    """Differing employee_id on same engagement must abort (not drop)."""
    await _ensure_engagement(test_db_session, 91025)
    await _insert_partner(
        test_db_session, partner_id=49, name="Madhu Pawar", phone="9420661939"
    )
    await _insert_partner(
        test_db_session, partner_id=58, name="Madhu Pawar", phone="94206 61939"
    )
    await test_db_session.execute(
        text(
            "ALTER TABLE onboarding_assistant_assignment "
            "DROP CONSTRAINT IF EXISTS ck_oa_assignment_partner_xor_employee"
        )
    )
    try:
        await test_db_session.execute(
            text(
                """
                INSERT INTO onboarding_assistant_assignment
                    (onboarding_assistant_id, partner_id, employee_id, engagement_id)
                VALUES (91011, 49, 1, 91025)
                """
            )
        )
        await test_db_session.execute(
            text(
                """
                INSERT INTO onboarding_assistant_assignment
                    (onboarding_assistant_id, partner_id, employee_id, engagement_id)
                VALUES (91012, 58, 2, 91025)
                """
            )
        )
        await test_db_session.commit()

        with pytest.raises(RuntimeError, match="onboarding_assistant_assignment conflict"):
            async with test_engine.begin() as conn:
                await conn.run_sync(_run_consolidate)
    finally:
        await test_db_session.execute(
            text(
                "DELETE FROM onboarding_assistant_assignment "
                "WHERE onboarding_assistant_id IN (91011, 91012)"
            )
        )
        await test_db_session.execute(
            text(
                """
                ALTER TABLE onboarding_assistant_assignment
                DROP CONSTRAINT IF EXISTS ck_oa_assignment_partner_xor_employee
                """
            )
        )
        await test_db_session.execute(
            text(
                """
                ALTER TABLE onboarding_assistant_assignment
                ADD CONSTRAINT ck_oa_assignment_partner_xor_employee
                CHECK (
                    (partner_id IS NOT NULL AND employee_id IS NULL) OR
                    (partner_id IS NULL AND employee_id IS NOT NULL)
                )
                """
            )
        )
        await test_db_session.commit()


@pytest.mark.asyncio
async def test_unapproved_collision_aborts(
    test_db_session, test_engine, drop_partners_phone_role_unique
):
    await _insert_partner(
        test_db_session,
        partner_id=501,
        name="Unknown A",
        phone="9111111111",
    )
    await _insert_partner(
        test_db_session,
        partner_id=502,
        name="Unknown B",
        phone="91111 11111",
    )
    await test_db_session.commit()

    def _abort(sync_conn):
        migration_0219.consolidate_approved_duplicates(sync_conn)
        migration_0219._abort_unapproved_phone_role_dupes(sync_conn)

    with pytest.raises(RuntimeError, match="NOT auto-merged"):
        async with test_engine.begin() as conn:
            await conn.run_sync(_abort)


@pytest.mark.asyncio
async def test_approved_name_conflict_logged_keeps_kept_values(
    test_db_session, test_engine, drop_partners_phone_role_unique
):
    await _insert_partner(
        test_db_session,
        partner_id=92,
        name="Pramod",
        phone="+919971574721",
        email="pramod-keep@example.com",
    )
    await _insert_partner(
        test_db_session,
        partner_id=122,
        name="Pramod Kumar",
        phone="9971574721",
        email="pramod-remove@example.com",
    )
    await test_db_session.commit()

    async with test_engine.begin() as conn:
        reports = await conn.run_sync(_run_consolidate)

    assert len(reports) == 1
    diffs = reports[0]["field_diffs"]
    assert any("name:" in d for d in diffs)
    assert any("email:" in d for d in diffs)

    row = (
        await test_db_session.execute(
            text("SELECT name, email, phone FROM partners WHERE partner_id = 92")
        )
    ).fetchone()
    assert row is not None
    assert row[0] == "Pramod"
    assert row[1] == "pramod-keep@example.com"
    assert row[2] == "+919971574721"
    gone = await test_db_session.execute(
        text("SELECT 1 FROM partners WHERE partner_id = 122")
    )
    assert gone.scalar() is None


@pytest.mark.asyncio
async def test_consolidator_noop_when_no_approved_pairs(test_db_session, test_engine):
    await _insert_partner(
        test_db_session,
        partner_id=777,
        name="Solo",
        phone="+919999999999",
    )
    await test_db_session.commit()

    async with test_engine.begin() as conn:
        reports = await conn.run_sync(_run_consolidate)

    assert reports == []
