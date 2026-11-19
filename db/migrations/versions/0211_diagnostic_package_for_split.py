"""Split test-group package_for enum; add both to diagnostic packages; backfill and dedupe.

Revision ID: 0211_diag_package_for_split
Revises: 0210_merge_0209_heads
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0211_diag_package_for_split"
down_revision = "0210_merge_0209_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    connection = bind

    op.execute(
        """
        DO $$ BEGIN
            ALTER TYPE package_for_enum ADD VALUE 'both';
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$
        """
    )

    test_group_pf = postgresql.ENUM("package", "public", "both", name="test_group_package_for_enum", create_type=True)
    test_group_pf.create(connection, checkfirst=True)

    op.execute(
        """
        ALTER TABLE diagnostic_test_groups
        ALTER COLUMN package_for DROP DEFAULT
        """
    )
    op.execute(
        """
        ALTER TABLE diagnostic_test_groups
        ALTER COLUMN package_for TYPE test_group_package_for_enum
        USING (
            CASE package_for::text
                WHEN 'camp' THEN 'package'::test_group_package_for_enum
                WHEN 'public' THEN 'public'::test_group_package_for_enum
                ELSE 'public'::test_group_package_for_enum
            END
        )
        """
    )
    op.execute(
        """
        ALTER TABLE diagnostic_test_groups
        ALTER COLUMN package_for SET DEFAULT 'public'::test_group_package_for_enum
        """
    )

    # Backfill A: assigned -> both; unassigned stays public; camp already mapped to package
    op.execute(
        """
        UPDATE diagnostic_test_groups g
        SET package_for = 'both'
        WHERE EXISTS (
            SELECT 1 FROM diagnostic_package_test_groups ptg
            WHERE ptg.group_id = g.group_id
        )
        """
    )

    # Deduplicate catalog groups: same tests + same provider (keep lowest group_id)
    op.execute(
        """
        WITH catalog AS (
            SELECT g.group_id,
                   COALESCE(g.diagnostic_provider::text, '') AS provider_key,
                   COALESCE(
                       (SELECT string_agg(t.test_id::text, ',' ORDER BY t.test_id)
                        FROM diagnostic_test_group_tests t
                        WHERE t.group_id = g.group_id),
                       ''
                   ) AS test_sig
            FROM diagnostic_test_groups g
            WHERE g.forked_from_group_id IS NULL
        ),
        pairs AS (
            SELECT LEAST(a.group_id, b.group_id) AS keep_id,
                   GREATEST(a.group_id, b.group_id) AS drop_id
            FROM catalog a
            JOIN catalog b ON a.group_id < b.group_id
             AND a.test_sig = b.test_sig
             AND a.test_sig <> ''
             AND a.provider_key = b.provider_key
        ),
        distinct_drop AS (
            SELECT drop_id, MIN(keep_id) AS keep_id
            FROM pairs
            GROUP BY drop_id
        )
        UPDATE diagnostic_package_test_groups ptg
        SET group_id = d.keep_id
        FROM distinct_drop d
        WHERE ptg.group_id = d.drop_id
          AND NOT EXISTS (
              SELECT 1 FROM diagnostic_package_test_groups x
              WHERE x.diagnostic_package_id = ptg.diagnostic_package_id
                AND x.group_id = d.keep_id
          )
        """
    )
    op.execute(
        """
        WITH catalog AS (
            SELECT g.group_id,
                   COALESCE(g.diagnostic_provider::text, '') AS provider_key,
                   COALESCE(
                       (SELECT string_agg(t.test_id::text, ',' ORDER BY t.test_id)
                        FROM diagnostic_test_group_tests t
                        WHERE t.group_id = g.group_id),
                       ''
                   ) AS test_sig
            FROM diagnostic_test_groups g
            WHERE g.forked_from_group_id IS NULL
        ),
        pairs AS (
            SELECT LEAST(a.group_id, b.group_id) AS keep_id,
                   GREATEST(a.group_id, b.group_id) AS drop_id
            FROM catalog a
            JOIN catalog b ON a.group_id < b.group_id
             AND a.test_sig = b.test_sig
             AND a.test_sig <> ''
             AND a.provider_key = b.provider_key
        ),
        distinct_drop AS (
            SELECT drop_id, MIN(keep_id) AS keep_id
            FROM pairs
            GROUP BY drop_id
        )
        DELETE FROM diagnostic_package_test_groups ptg
        USING distinct_drop d
        WHERE ptg.group_id = d.drop_id
        """
    )
    op.execute(
        """
        WITH catalog AS (
            SELECT g.group_id,
                   COALESCE(g.diagnostic_provider::text, '') AS provider_key,
                   COALESCE(
                       (SELECT string_agg(t.test_id::text, ',' ORDER BY t.test_id)
                        FROM diagnostic_test_group_tests t
                        WHERE t.group_id = g.group_id),
                       ''
                   ) AS test_sig
            FROM diagnostic_test_groups g
            WHERE g.forked_from_group_id IS NULL
        ),
        pairs AS (
            SELECT GREATEST(a.group_id, b.group_id) AS drop_id
            FROM catalog a
            JOIN catalog b ON a.group_id < b.group_id
             AND a.test_sig = b.test_sig
             AND a.test_sig <> ''
             AND a.provider_key = b.provider_key
        )
        DELETE FROM diagnostic_test_group_tests t
        USING pairs p
        WHERE t.group_id = p.drop_id
        """
    )
    op.execute(
        """
        WITH catalog AS (
            SELECT g.group_id,
                   COALESCE(g.diagnostic_provider::text, '') AS provider_key,
                   COALESCE(
                       (SELECT string_agg(t.test_id::text, ',' ORDER BY t.test_id)
                        FROM diagnostic_test_group_tests t
                        WHERE t.group_id = g.group_id),
                       ''
                   ) AS test_sig
            FROM diagnostic_test_groups g
            WHERE g.forked_from_group_id IS NULL
        ),
        pairs AS (
            SELECT GREATEST(a.group_id, b.group_id) AS drop_id
            FROM catalog a
            JOIN catalog b ON a.group_id < b.group_id
             AND a.test_sig = b.test_sig
             AND a.test_sig <> ''
             AND a.provider_key = b.provider_key
        )
        DELETE FROM diagnostic_test_groups g
        USING pairs p
        WHERE g.group_id = p.drop_id
        """
    )

    # Collapse forks that match catalog signature + provider: point assignments at catalog, delete fork
    op.execute(
        """
        WITH sig AS (
            SELECT g.group_id,
                   g.forked_from_group_id,
                   COALESCE(g.diagnostic_provider::text, '') AS provider_key,
                   COALESCE(
                       (SELECT string_agg(t.test_id::text, ',' ORDER BY t.test_id)
                        FROM diagnostic_test_group_tests t
                        WHERE t.group_id = g.group_id),
                       ''
                   ) AS test_sig
            FROM diagnostic_test_groups g
        ),
        matches AS (
            SELECT f.group_id AS fork_id, c.group_id AS catalog_id
            FROM sig f
            JOIN sig c ON c.forked_from_group_id IS NULL
             AND f.forked_from_group_id IS NOT NULL
             AND f.test_sig = c.test_sig
             AND f.test_sig <> ''
             AND f.provider_key = c.provider_key
        )
        UPDATE diagnostic_package_test_groups ptg
        SET group_id = m.catalog_id
        FROM matches m
        WHERE ptg.group_id = m.fork_id
          AND NOT EXISTS (
              SELECT 1 FROM diagnostic_package_test_groups x
              WHERE x.diagnostic_package_id = ptg.diagnostic_package_id
                AND x.group_id = m.catalog_id
          )
        """
    )
    op.execute(
        """
        WITH sig AS (
            SELECT g.group_id,
                   g.forked_from_group_id,
                   COALESCE(g.diagnostic_provider::text, '') AS provider_key,
                   COALESCE(
                       (SELECT string_agg(t.test_id::text, ',' ORDER BY t.test_id)
                        FROM diagnostic_test_group_tests t
                        WHERE t.group_id = g.group_id),
                       ''
                   ) AS test_sig
            FROM diagnostic_test_groups g
        ),
        matches AS (
            SELECT f.group_id AS fork_id
            FROM sig f
            JOIN sig c ON c.forked_from_group_id IS NULL
             AND f.forked_from_group_id IS NOT NULL
             AND f.test_sig = c.test_sig
             AND f.test_sig <> ''
             AND f.provider_key = c.provider_key
        )
        DELETE FROM diagnostic_package_test_groups ptg
        USING matches m
        WHERE ptg.group_id = m.fork_id
        """
    )
    op.execute(
        """
        WITH sig AS (
            SELECT g.group_id,
                   g.forked_from_group_id,
                   COALESCE(g.diagnostic_provider::text, '') AS provider_key,
                   COALESCE(
                       (SELECT string_agg(t.test_id::text, ',' ORDER BY t.test_id)
                        FROM diagnostic_test_group_tests t
                        WHERE t.group_id = g.group_id),
                       ''
                   ) AS test_sig
            FROM diagnostic_test_groups g
        ),
        matches AS (
            SELECT f.group_id AS fork_id
            FROM sig f
            JOIN sig c ON c.forked_from_group_id IS NULL
             AND f.forked_from_group_id IS NOT NULL
             AND f.test_sig = c.test_sig
             AND f.test_sig <> ''
             AND f.provider_key = c.provider_key
        )
        DELETE FROM diagnostic_test_group_tests t
        USING matches m
        WHERE t.group_id = m.fork_id
        """
    )
    op.execute(
        """
        WITH sig AS (
            SELECT g.group_id,
                   g.forked_from_group_id,
                   COALESCE(g.diagnostic_provider::text, '') AS provider_key,
                   COALESCE(
                       (SELECT string_agg(t.test_id::text, ',' ORDER BY t.test_id)
                        FROM diagnostic_test_group_tests t
                        WHERE t.group_id = g.group_id),
                       ''
                   ) AS test_sig
            FROM diagnostic_test_groups g
        ),
        matches AS (
            SELECT f.group_id AS fork_id
            FROM sig f
            JOIN sig c ON c.forked_from_group_id IS NULL
             AND f.forked_from_group_id IS NOT NULL
             AND f.test_sig = c.test_sig
             AND f.test_sig <> ''
             AND f.provider_key = c.provider_key
        )
        DELETE FROM diagnostic_test_groups g
        USING matches m
        WHERE g.group_id = m.fork_id
          AND NOT EXISTS (
              SELECT 1 FROM diagnostic_package_test_groups ptg WHERE ptg.group_id = g.group_id
          )
        """
    )

    # Forked groups still assigned should be package-only audience
    op.execute(
        """
        UPDATE diagnostic_test_groups
        SET package_for = 'package'
        WHERE forked_from_group_id IS NOT NULL
        """
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported for 0211_diag_package_for_split")