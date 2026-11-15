"""Migrate notification module tests: webhook_path seeds + httpx mocks → direct dispatch."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "tests" / "modules" / "notifications"

IMPORT = "from tests.modules.notifications.dispatch_mocks import patch_service_direct_deliver\n"


def _ensure_import(text: str) -> str:
    if "dispatch_mocks import" in text:
        return text
    m = re.search(r"(from modules\.[^\n]+\n|from tests\.[^\n]+\n)(?=\n[^\n]*\n)", text)
    if m:
        return text[: m.end()] + "\n" + IMPORT + text[m.end() :]
    return IMPORT + text


def _remove_n8n_autouse(text: str) -> str:
    return re.sub(
        r"@pytest\.fixture\(autouse=True\)\ndef _[a-z_]*n8n[a-z_]*\(monkeypatch\):[\s\S]*?\n\n",
        "",
        text,
        flags=re.I,
    )


def _replace_httpx_blocks(text: str) -> str:
    text = text.replace("webhook_calls", "deliver_calls")
    text = text.replace('deliver_calls[0]["json"]["members"]', 'deliver_calls[0]["members"]')
    text = text.replace('call["json"]["members"]', 'call["members"]')
    text = re.sub(
        r'deliver_calls\[0\]\["json"\]',
        'deliver_calls[0]',
        text,
    )
    text = re.sub(
        r'    deliver_calls: list\[dict\] = \[\]\n\n    class _FakeResponse:[\s\S]*?'
        r'monkeypatch\.setattr\("modules\.notifications\.service\.httpx\.AsyncClient", _FakeClient\)\n',
        "    deliver_calls: list[dict] = []\n    patch_service_direct_deliver(monkeypatch, deliver_calls)\n",
        text,
    )
    text = re.sub(
        r'monkeypatch\.setattr\(\s*"modules\.notifications\.service\.httpx\.AsyncClient",\s*_fake_httpx_client\(deliver_calls\),\s*\)',
        "patch_service_direct_deliver(monkeypatch, deliver_calls)",
        text,
    )
    text = re.sub(
        r"\ndef _fake_httpx_client\([\s\S]*?return _FakeClient\n\n",
        "\n",
        text,
    )
    return text


def _webhook_column_to_direct(text: str) -> str:
    """channel, webhook_path -> template_name OR email_subject/email_body."""

    # Standard parameterized insert
    text = re.sub(
        r"\(service_key, display_name, channel, webhook_path, is_active",
        "(service_key, display_name, channel, template_name, email_subject, email_body, is_active",
        text,
    )
    text = re.sub(
        r"\(service_key, display_name, channel, webhook_path, is_active, require_otp\)",
        "(service_key, display_name, channel, template_name, email_subject, email_body, is_active, require_otp)",
        text,
    )
    text = re.sub(
        r"channel, webhook_path, is_active",
        "channel, template_name, email_subject, email_body, is_active",
        text,
    )
    text = re.sub(
        r"VALUES \(:service_key, :display_name, :channel, :webhook_path,",
        "VALUES (:service_key, :display_name, :channel, :template_name, :email_subject, :email_body,",
        text,
    )
    text = re.sub(
        r"VALUES \(:sk, :dn, :ch, :wp,",
        "VALUES (:sk, :dn, :ch, :template_name, :email_subject, :email_body,",
        text,
    )
    # For loops: for ... webhook_path -> template_label
    text = re.sub(
        r"for (\w+), channel, webhook_path in",
        r"for \1, channel, template_label in",
        text,
    )
    text = re.sub(
        r"for service_key, channel, webhook_path in",
        "for service_key, channel, template_label in",
        text,
    )
    text = re.sub(r'\{"sk": service_key, "dn": service_key, "ch": channel, "wp": webhook_path\}', 
                  '{"sk": service_key, "dn": service_key, "ch": channel, "template_name": template_label, "email_subject": "Test", "email_body": "Test"}', text)
    text = re.sub(
        r'"wp": webhook_path',
        '"template_name": template_label, "email_subject": "Test", "email_body": "Test"',
        text,
    )
    text = re.sub(
        r"webhook_path = EXCLUDED\.webhook_path",
        "template_name = EXCLUDED.template_name",
        text,
    )
    text = re.sub(
        r'"webhook_path":\s*webhook_path',
        '"template_name": template_label, "email_subject": "Test", "email_body": "Test"',
        text,
    )
    return text


def fix_file(path: Path) -> bool:
    if path.name in ("dispatch_mocks.py", "conftest.py"):
        return False
    text = path.read_text(encoding="utf-8")
    orig = text
    text = _remove_n8n_autouse(text)
    text = _webhook_column_to_direct(text)
    text = _replace_httpx_blocks(text)
    text = text.replace("test_provider", "healthians")
    if "patch_service_direct_deliver" in text or "deliver_calls" in text:
        text = _ensure_import(text)
    if text != orig:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> None:
    n = 0
    for p in sorted(ROOT.glob("test_*.py")):
        if fix_file(p):
            n += 1
            print("fixed", p.name)
    print("total", n)


if __name__ == "__main__":
    main()