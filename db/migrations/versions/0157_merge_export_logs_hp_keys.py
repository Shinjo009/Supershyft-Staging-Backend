"""Merge export_logs reshape and health parameter provider key heads.

Revision ID: 0157_merge_export_logs_hp_keys
Revises: 0156_export_logs_reshape, 0156_hp_provider_keys
"""

from __future__ import annotations

revision = "0157_merge_export_logs_hp_keys"
down_revision = ("0156_export_logs_reshape", "0156_hp_provider_keys")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
