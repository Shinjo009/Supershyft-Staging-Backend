"""Merge same-test groups across providers into one profile group; drop redundant forks.

Revision ID: 0212_profile_variants
Revises: 0211_diag_package_for_split
"""

from __future__ import annotations

from alembic import op

revision = "0212_profile_variants"
down_revision = "0211_diag_package_for_split"
branch_labels = None
depends_on = None

_TEST_SIG_EXPR = """
COALESCE(
    (SELECT string_agg(t.test_id::text, ',' ORDER BY t.test_id)
     FROM diagnostic_test_group_tests t
     WHERE t.group_id = g.group_id),
    ''
)
"""


def _dedupe_sig_cte() -> str:
    return f"""
        sig AS (
            SELECT g.group_id,
                   g.forked_from_group_id,
                   COALESCE(g.diagnostic_provider::text, '') AS provider_key,
                   {_TEST_SIG_EXPR} AS test_sig,
                   EXISTS (
                       SELECT 1 FROM diagnostic_package_test_groups ptg
                       WHERE ptg.group_id = g.group_id
                   ) AS has_pkg,
                   (g.external_test_group_code IS NOT NULL) AS has_code
            FROM diagnostic_test_groups g
        ),
        keepers AS (
            SELECT DISTINCT ON (test_sig, provider_key)
                   group_id AS keep_id,
                   test_sig,
                   provider_key
            FROM sig
            WHERE test_sig <> ''
            ORDER BY test_sig,
                     provider_key,
                     CASE WHEN forked_from_group_id IS NULL THEN 0 ELSE 1 END,
                     CASE WHEN has_pkg THEN 0 ELSE 1 END,
                     CASE WHEN has_code THEN 0 ELSE 1 END,
                     group_id
        ),
        droppers AS (
            SELECT s.group_id AS drop_id,
                   k.keep_id
            FROM sig s
            JOIN keepers k
              ON k.test_sig = s.test_sig
             AND k.provider_key = s.provider_key
            WHERE s.group_id <> k.keep_id
        )
    """


def upgrade() -> None:
    # Ensure each test-set anchor has a profile_group_id (create one when missing).
    op.execute(
        f"""
        DO $$
        DECLARE
            rec RECORD;
            new_pg_id INTEGER;
        BEGIN
            FOR rec IN
                WITH sig AS (
                    SELECT g.group_id,
                           g.profile_group_id,
                           g.forked_from_group_id,
                           g.is_default_for_group,
                           {_TEST_SIG_EXPR} AS test_sig
                    FROM diagnostic_test_groups g
                ),
                anchors AS (
                    SELECT DISTINCT ON (test_sig)
                           group_id AS anchor_id,
                           profile_group_id AS anchor_pg,
                           test_sig
                    FROM sig
                    WHERE test_sig <> ''
                    ORDER BY test_sig,
                        CASE WHEN forked_from_group_id IS NULL THEN 0 ELSE 1 END,
                        CASE WHEN is_default_for_group THEN 0 ELSE 1 END,
                        group_id
                )
                SELECT anchor_id
                FROM anchors
                WHERE anchor_pg IS NULL
            LOOP
                INSERT INTO diagnostic_profile_group DEFAULT VALUES
                RETURNING profile_group_id INTO new_pg_id;
                UPDATE diagnostic_test_groups
                SET profile_group_id = new_pg_id
                WHERE group_id = rec.anchor_id;
            END LOOP;
        END $$
        """
    )

    # Pick one survivor per (test_sig, provider); reassign package rows; drop duplicates.
    op.execute(
        f"""
        WITH {_dedupe_sig_cte()}
        UPDATE diagnostic_package_test_groups ptg
        SET group_id = d.keep_id
        FROM droppers d
        WHERE ptg.group_id = d.drop_id
          AND NOT EXISTS (
              SELECT 1 FROM diagnostic_package_test_groups x
              WHERE x.diagnostic_package_id = ptg.diagnostic_package_id
                AND x.group_id = d.keep_id
          )
        """
    )
    for delete_sql in (
        "DELETE FROM diagnostic_package_test_groups ptg USING droppers d WHERE ptg.group_id = d.drop_id",
        "DELETE FROM diagnostic_test_group_tests t USING droppers d WHERE t.group_id = d.drop_id",
        "DELETE FROM diagnostic_package_filter_chip_links l USING droppers d WHERE l.group_id = d.drop_id",
        "DELETE FROM diagnostic_test_groups g USING droppers d WHERE g.group_id = d.drop_id",
    ):
        op.execute(
            f"""
            WITH {_dedupe_sig_cte()}
            {delete_sql}
            """
        )

    # Partial unique index uq_diagnostic_test_group_one_default_per_profile allows only one
    # default per profile_group_id; clear defaults before merging profiles, then re-rank below.
    op.execute(
        """
        UPDATE diagnostic_test_groups
        SET is_default_for_group = false
        WHERE is_default_for_group = true
        """
    )

    # Move all survivors for the same test set into the anchor profile group.
    op.execute(
        f"""
        WITH sig AS (
            SELECT g.group_id,
                   g.profile_group_id,
                   g.forked_from_group_id,
                   g.is_default_for_group,
                   {_TEST_SIG_EXPR} AS test_sig
            FROM diagnostic_test_groups g
        ),
        anchors AS (
            SELECT DISTINCT ON (test_sig)
                   test_sig,
                   group_id AS anchor_group_id,
                   profile_group_id AS anchor_pg
            FROM sig
            WHERE test_sig <> ''
            ORDER BY test_sig,
                     CASE WHEN forked_from_group_id IS NULL THEN 0 ELSE 1 END,
                     CASE WHEN is_default_for_group THEN 0 ELSE 1 END,
                     group_id
        )
        UPDATE diagnostic_test_groups g
        SET profile_group_id = a.anchor_pg
        FROM sig s
        JOIN anchors a ON a.test_sig = s.test_sig
        WHERE g.group_id = s.group_id
          AND s.test_sig <> ''
          AND a.anchor_pg IS NOT NULL
        """
    )

    # Promote redundant forks (same tests as parent) to catalog variants; keep customized package forks.
    op.execute(
        f"""
        WITH child AS (
            SELECT g.group_id,
                   g.forked_from_group_id,
                   {_TEST_SIG_EXPR} AS test_sig
            FROM diagnostic_test_groups g
            WHERE g.forked_from_group_id IS NOT NULL
        ),
        parent AS (
            SELECT g.group_id,
                   {_TEST_SIG_EXPR} AS test_sig
            FROM diagnostic_test_groups g
        )
        UPDATE diagnostic_test_groups g
        SET forked_from_group_id = NULL
        FROM child c
        JOIN parent p ON p.group_id = c.forked_from_group_id
        WHERE g.group_id = c.group_id
          AND c.test_sig <> ''
          AND c.test_sig = p.test_sig
        """
    )

    # When different catalog groups shared a test set but lived in different profile groups, fold extras in.
    op.execute(
        """
        WITH sig AS (
            SELECT g.group_id,
                   g.profile_group_id,
                   COALESCE(
                       (SELECT string_agg(t.test_id::text, ',' ORDER BY t.test_id)
                        FROM diagnostic_test_group_tests t
                        WHERE t.group_id = g.group_id),
                       ''
                   ) AS test_sig
            FROM diagnostic_test_groups g
            WHERE g.forked_from_group_id IS NULL
        ),
        anchors AS (
            SELECT DISTINCT ON (test_sig)
                   test_sig,
                   profile_group_id AS anchor_pg
            FROM sig
            WHERE test_sig <> '' AND profile_group_id IS NOT NULL
            ORDER BY test_sig, group_id
        )
        UPDATE diagnostic_test_groups g
        SET profile_group_id = a.anchor_pg
        FROM sig s
        JOIN anchors a ON a.test_sig = s.test_sig
        WHERE g.group_id = s.group_id
          AND g.profile_group_id IS DISTINCT FROM a.anchor_pg
        """
    )

    # One default catalog row per profile group (prefer existing default, else lowest catalog id).
    op.execute(
        """
        WITH ranked AS (
            SELECT g.group_id,
                   g.profile_group_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY g.profile_group_id
                       ORDER BY
                           CASE WHEN g.is_default_for_group THEN 0 ELSE 1 END,
                           CASE WHEN g.forked_from_group_id IS NULL THEN 0 ELSE 1 END,
                           g.group_id
                   ) AS rn
            FROM diagnostic_test_groups g
            WHERE g.profile_group_id IS NOT NULL
        )
        UPDATE diagnostic_test_groups g
        SET is_default_for_group = (r.rn = 1)
        FROM ranked r
        WHERE g.group_id = r.group_id
        """
    )

    # Catalog rows: public when unassigned, both when on any package.
    op.execute(
        """
        UPDATE diagnostic_test_groups g
        SET package_for = CASE
            WHEN EXISTS (
                SELECT 1 FROM diagnostic_package_test_groups ptg
                WHERE ptg.group_id = g.group_id
            ) THEN 'both'::test_group_package_for_enum
            ELSE 'public'::test_group_package_for_enum
        END
        WHERE g.forked_from_group_id IS NULL
        """
    )

    # Reassign packages to the provider-matching variant when the assigned group provider mismatches.
    op.execute(
        """
        WITH ptg AS (
            SELECT ptg.id,
                   ptg.diagnostic_package_id,
                   ptg.group_id,
                   p.diagnostic_provider AS pkg_provider,
                   g.profile_group_id,
                   g.diagnostic_provider AS grp_provider
            FROM diagnostic_package_test_groups ptg
            JOIN diagnostic_package p
              ON p.diagnostic_package_id = ptg.diagnostic_package_id
            JOIN diagnostic_test_groups g ON g.group_id = ptg.group_id
        ),
        desired AS (
            SELECT ptg.id,
                   alt.group_id AS new_group_id
            FROM ptg
            JOIN diagnostic_test_groups alt
              ON alt.profile_group_id = ptg.profile_group_id
             AND alt.forked_from_group_id IS NULL
             AND (
                 (ptg.pkg_provider IS NULL AND alt.diagnostic_provider IS NULL)
                 OR alt.diagnostic_provider = ptg.pkg_provider
             )
            WHERE ptg.profile_group_id IS NOT NULL
              AND ptg.grp_provider IS DISTINCT FROM ptg.pkg_provider
        )
        UPDATE diagnostic_package_test_groups ptg
        SET group_id = d.new_group_id
        FROM desired d
        WHERE ptg.id = d.id
          AND NOT EXISTS (
              SELECT 1 FROM diagnostic_package_test_groups x
              WHERE x.diagnostic_package_id = ptg.diagnostic_package_id
                AND x.group_id = d.new_group_id
          )
        """
    )

    op.execute(
        """
        DELETE FROM diagnostic_profile_group pg
        WHERE NOT EXISTS (
            SELECT 1 FROM diagnostic_test_groups g
            WHERE g.profile_group_id = pg.profile_group_id
        )
        """
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported for 0212_profile_variants")