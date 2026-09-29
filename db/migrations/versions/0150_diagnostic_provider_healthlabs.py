"""Add HealthLabs to diagnostic_provider_enum for sample seed data.

Revision ID: 0150_healthlabs_provider
Revises: 0149_column_type_optimization
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "0150_healthlabs_provider"
down_revision = "0149_column_type_optimization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("ALTER TYPE diagnostic_provider_enum ADD VALUE IF NOT EXISTS 'HealthLabs'"))


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
