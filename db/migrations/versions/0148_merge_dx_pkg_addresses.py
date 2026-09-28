"""Merge gender diagnostic packages with user addresses.

Revision ID: 0148_merge_dx_pkg_addresses
Revises: 0147_eng_gender_dx_pkg, 0147_user_addresses
"""

from __future__ import annotations

revision = "0148_merge_dx_pkg_addresses"
down_revision = ("0147_eng_gender_dx_pkg", "0147_user_addresses")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
