"""Add google_maps and nominatim to integration_provider_enum for geocode sync logs.

Revision ID: 0153_geocoding_sync_providers
Revises: 0152_geocoding_provider
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "0153_geocoding_sync_providers"
down_revision = "0152_geocoding_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("ALTER TYPE integration_provider_enum ADD VALUE IF NOT EXISTS 'google_maps'"))
    op.execute(text("ALTER TYPE integration_provider_enum ADD VALUE IF NOT EXISTS 'nominatim'"))


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
