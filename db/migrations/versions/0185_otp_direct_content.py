"""Seed direct OTP content on notification_services (WhatAPI POST + SMTP).

Revision ID: 0185_otp_direct_content
Revises: 0184_notif_rebuild
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0185_otp_direct_content"
down_revision = "0184_notif_rebuild"
branch_labels = None
depends_on = None

_WHATAPI_OTP_TEMPLATE_VARS = json.dumps(
    [
        {
            "component": "body",
            "parameters": [{"type": "text", "source": "{{otp.otp}}"}],
        }
    ]
)


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("ALTER TYPE integration_provider_enum ADD VALUE IF NOT EXISTS 'whatapi'")
    )
    conn.execute(
        sa.text(
            """
            UPDATE notification_services
            SET template_name = 'otp_new',
                template_variables = CAST(:vars AS jsonb)
            WHERE service_key = 'whatapi-otp'
            """
        ),
        {"vars": _WHATAPI_OTP_TEMPLATE_VARS},
    )
    conn.execute(
        sa.text(
            """
            UPDATE notification_services
            SET email_subject = 'Your Supershyft verification code',
                email_body = 'Your verification code is {{otp}}. It expires in 10 minutes.'
            WHERE service_key = 'email-otp'
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE notification_services
            SET template_name = NULL,
                template_variables = NULL
            WHERE service_key = 'whatapi-otp'
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE notification_services
            SET email_subject = NULL,
                email_body = NULL,
                email_html = NULL
            WHERE service_key = 'email-otp'
            """
        )
    )
