"""Apply committed 0187 notification_services content artifact."""

from __future__ import annotations

import json
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

_ARTIFACT = Path(__file__).resolve().parents[2] / "db" / "migrations" / "data" / "0187_notification_content.json"

_WHATAPI_OTP_VARS = json.dumps(
    [
        {
            "component": "body",
            "parameters": [{"type": "text", "source": "{{otp.otp}}"}],
        }
    ]
)


def _load_rows() -> list[dict]:
    if not _ARTIFACT.is_file():
        return []
    return json.loads(_ARTIFACT.read_text(encoding="utf-8"))


def apply_notification_content_backfill_sync(conn) -> None:
    """Sync SQLAlchemy connection (Alembic migration)."""
    for row in _load_rows():
        _apply_row(conn.execute, row)


async def apply_notification_content_backfill(session: AsyncSession) -> None:
    """Async session (db seed after upsert)."""

    async def execute(statement, params=None):
        return await session.execute(statement, params or {})

    for row in _load_rows():
        await _apply_row_async(execute, row)


def _apply_row(execute, row: dict) -> None:
    service_key = row.get("service_key")
    if not service_key:
        return
    if service_key == "whatapi-otp":
        execute(
            sa.text(
                """
                UPDATE notification_services
                SET template_name = 'otp_new',
                    template_variables = CAST(:vars AS jsonb)
                WHERE service_key = 'whatapi-otp'
                """
            ),
            {"vars": _WHATAPI_OTP_VARS},
        )
        return
    params: dict = {"service_key": service_key}
    sets: list[str] = []
    if row.get("template_name"):
        sets.append("template_name = :template_name")
        params["template_name"] = row["template_name"]
    if row.get("template_variables") is not None:
        sets.append("template_variables = CAST(:template_variables AS jsonb)")
        params["template_variables"] = json.dumps(row["template_variables"])
    if row.get("email_subject"):
        sets.append("email_subject = :email_subject")
        params["email_subject"] = row["email_subject"]
    if row.get("email_body"):
        sets.append("email_body = :email_body")
        params["email_body"] = row["email_body"]
    if row.get("email_html"):
        sets.append("email_html = :email_html")
        params["email_html"] = row["email_html"]
    if not sets:
        return
    execute(
        sa.text(f"UPDATE notification_services SET {', '.join(sets)} WHERE service_key = :service_key"),
        params,
    )


async def _apply_row_async(execute, row: dict) -> None:
    service_key = row.get("service_key")
    if not service_key:
        return
    if service_key == "whatapi-otp":
        await execute(
            sa.text(
                """
                UPDATE notification_services
                SET template_name = 'otp_new',
                    template_variables = CAST(:vars AS jsonb)
                WHERE service_key = 'whatapi-otp'
                """
            ),
            {"vars": _WHATAPI_OTP_VARS},
        )
        return
    params: dict = {"service_key": service_key}
    sets: list[str] = []
    if row.get("template_name"):
        sets.append("template_name = :template_name")
        params["template_name"] = row["template_name"]
    if row.get("template_variables") is not None:
        sets.append("template_variables = CAST(:template_variables AS jsonb)")
        params["template_variables"] = json.dumps(row["template_variables"])
    if row.get("email_subject"):
        sets.append("email_subject = :email_subject")
        params["email_subject"] = row["email_subject"]
    if row.get("email_body"):
        sets.append("email_body = :email_body")
        params["email_body"] = row["email_body"]
    if row.get("email_html"):
        sets.append("email_html = :email_html")
        params["email_html"] = row["email_html"]
    if not sets:
        return
    await execute(
        sa.text(f"UPDATE notification_services SET {', '.join(sets)} WHERE service_key = :service_key"),
        params,
    )
