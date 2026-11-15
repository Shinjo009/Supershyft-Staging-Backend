"""Insert notification_services rows in tests (post-0209, no webhook_path)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_INSERT_SQL = """
INSERT INTO notification_services (
    service_key,
    display_name,
    channel,
    template_name,
    email_subject,
    email_body,
    is_active,
    require_blood_report_url,
    require_bio_ai_report_url,
    require_participant_detail,
    require_otp,
    require_session_details,
    require_external_link
) VALUES (
    :sk,
    :dn,
    :ch,
    :template_name,
    :email_subject,
    :email_body,
    true,
    false,
    false,
    false,
    false,
    false,
    false
)
ON CONFLICT (service_key) DO UPDATE SET is_active = true
"""


def service_insert_params(
    *,
    service_key: str,
    display_name: str | None = None,
    channel: str,
    template_name: str = "test_tpl",
    email_subject: str = "Test",
    email_body: str = "Test",
) -> dict:
    dn = display_name or service_key
    if channel == "whatsapp":
        return {
            "sk": service_key,
            "dn": dn,
            "ch": channel,
            "template_name": template_name,
            "email_subject": None,
            "email_body": None,
        }
    return {
        "sk": service_key,
        "dn": dn,
        "ch": channel,
        "template_name": None,
        "email_subject": email_subject,
        "email_body": email_body,
    }


async def insert_notification_service(
    session: AsyncSession,
    *,
    service_key: str,
    channel: str,
    display_name: str | None = None,
    template_name: str = "test_tpl",
    email_subject: str = "Test",
    email_body: str = "Test",
    extra_require_flags: dict | None = None,
) -> None:
    params = service_insert_params(
        service_key=service_key,
        display_name=display_name,
        channel=channel,
        template_name=template_name,
        email_subject=email_subject,
        email_body=email_body,
    )
    sql = _INSERT_SQL
    if extra_require_flags:
        sql = sql.replace(
            "false,\n    false,\n    false,\n    false,\n    false,\n    false",
            ", ".join(
                f":{k}" if k.startswith("require_") else "false"
                for k in extra_require_flags
            ),
        )
    await session.execute(text(sql), params)