"""Add subscription_id to assessment_packages for MetSights External API."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0155_pkg_subscription_id"
down_revision = "0154_orange_health"
branch_labels = None
depends_on = None

_SUB_ESSENTIALS = "01975457-63d4-c3eb-52f7-15bd67a7da7a"
_SUB_PRO = "01975457-778f-064b-78a5-6990afec7881"
_SUB_FITPRINT = "01975457-d2fb-54af-8795-55933c580979"


def upgrade() -> None:
    op.add_column(
        "assessment_packages",
        sa.Column("subscription_id", sa.String(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE assessment_packages "
            f"SET subscription_id = '{_SUB_ESSENTIALS}', display_name = 'MetSights Essentials' "
            "WHERE package_code = 'METSIGHTS_BASIC'"
        )
    )
    op.execute(
        sa.text(
            f"UPDATE assessment_packages SET subscription_id = '{_SUB_PRO}' "
            "WHERE package_code = 'METSIGHTS_PRO'"
        )
    )
    op.execute(
        sa.text(
            f"UPDATE assessment_packages SET subscription_id = '{_SUB_FITPRINT}' "
            "WHERE package_code = 'MY_FITNESS_PRINT'"
        )
    )


def downgrade() -> None:
    op.drop_column("assessment_packages", "subscription_id")
