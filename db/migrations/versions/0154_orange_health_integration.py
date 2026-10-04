"""Orange Health: provider enum, external codes, PBB provider fields.

Revision ID: 0154_orange_health
Revises: 0153_geocoding_sync_providers
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "0154_orange_health"
down_revision = "0153_geocoding_sync_providers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("ALTER TYPE diagnostic_provider_enum ADD VALUE IF NOT EXISTS 'orange_health'"))
    op.execute(text("ALTER TYPE integration_provider_enum ADD VALUE IF NOT EXISTS 'orange_health'"))

    op.execute(
        text(
            """
            DO $$ BEGIN
                CREATE TYPE blood_booking_provider_status_enum AS ENUM ('Scheduled');
            EXCEPTION
                WHEN duplicate_object THEN NULL;
            END $$;
            """
        )
    )

    op.execute(
        text(
            """
            ALTER TABLE diagnostic_package
            RENAME COLUMN external_package_id TO external_package_code;
            """
        )
    )
    op.execute(
        text(
            """
            ALTER TABLE diagnostic_package
            ALTER COLUMN external_package_code TYPE VARCHAR
            USING (
                CASE
                    WHEN external_package_code IS NULL THEN NULL
                    ELSE external_package_code::text
                END
            );
            """
        )
    )

    op.execute(
        text(
            """
            ALTER TABLE health_parameters
            RENAME COLUMN external_parameter_id TO external_parameter_code;
            """
        )
    )
    op.execute(
        text(
            """
            ALTER TABLE health_parameters
            ALTER COLUMN external_parameter_code TYPE VARCHAR
            USING (
                CASE
                    WHEN external_parameter_code IS NULL THEN NULL
                    ELSE external_parameter_code::text
                END
            );
            """
        )
    )

    op.execute(
        text(
            """
            ALTER TABLE participant_blood_bookings
            ADD COLUMN IF NOT EXISTS diagnostic_provider diagnostic_provider_enum NULL,
            ADD COLUMN IF NOT EXISTS request_id VARCHAR NULL,
            ADD COLUMN IF NOT EXISTS token VARCHAR NULL,
            ADD COLUMN IF NOT EXISTS order_id BIGINT NULL,
            ADD COLUMN IF NOT EXISTS alnum_order_id VARCHAR NULL,
            ADD COLUMN IF NOT EXISTS provider_status blood_booking_provider_status_enum NULL;
            """
        )
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
