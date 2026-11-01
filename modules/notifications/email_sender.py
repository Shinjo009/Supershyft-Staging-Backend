"""SMTP email sender for direct notification delivery."""

from __future__ import annotations

import asyncio
import re
import smtplib
from email.message import EmailMessage

from core.config import settings

_PLACEHOLDER = re.compile(r"\{\{(\w+(?:\.\w+)*)\}\}")


def _interpolate(template: str, context: dict) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key == "otp":
            otp_ctx = context.get("otp")
            if isinstance(otp_ctx, dict):
                return str(otp_ctx.get("otp") or "")
            return str(context.get("otp") or "")
        parts = key.split(".")
        node: object = context
        for part in parts:
            if not isinstance(node, dict):
                return ""
            node = node.get(part)
        return "" if node is None else str(node)

    return _PLACEHOLDER.sub(repl, template)


def _send_smtp_sync(*, to_email: str, subject: str, body_text: str, body_html: str | None) -> None:
    if not settings.SMTP_HOST:
        raise ValueError("SMTP_HOST is not configured")
    msg = EmailMessage()
    from_addr = settings.SMTP_FROM_EMAIL or settings.SMTP_USERNAME
    msg["From"] = (
        f"{settings.SMTP_FROM_NAME} <{from_addr}>"
        if settings.SMTP_FROM_NAME
        else from_addr
    )
    msg["To"] = to_email
    msg["Subject"] = subject
    if body_html:
        msg.set_content(body_text or body_html, subtype="html")
    else:
        msg.set_content(body_text or "")

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.SMTP_TIMEOUT_SECONDS) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()
        if settings.SMTP_USERNAME:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(msg)


async def send_email(
    *,
    to_email: str,
    subject_template: str,
    body_template: str,
    html_template: str | None,
    context: dict,
) -> str:
    subject = _interpolate(subject_template, context)
    body = _interpolate(body_template, context)
    html = _interpolate(html_template, context) if html_template else None
    await asyncio.to_thread(
        _send_smtp_sync,
        to_email=to_email,
        subject=subject,
        body_text=body,
        body_html=html,
    )
    return f"Email sent via SMTP to {to_email}"
