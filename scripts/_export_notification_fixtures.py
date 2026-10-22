"""Read-only export notification_services + notification_events to JSON fixtures."""

from __future__ import annotations

import json
import os
import sys

import paramiko

HOST = "187.77.185.240"
USER = "pita-ihsir"
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "db", "fixtures")

REMOTE_PY = (
    "import asyncio, json\n"
    "from sqlalchemy import text\n"
    "from db.session import AsyncSessionLocal\n"
    "async def main():\n"
    "    async with AsyncSessionLocal() as db:\n"
    "        svc = await db.execute(text(\n"
    "            'SELECT service_key, display_name, channel, is_active, '\n"
    "            'template_name, template_variables, email_subject, email_body, email_html '\n"
    "            'FROM notification_services ORDER BY service_key'\n"
    "        ))\n"
    "        services = [dict(r._mapping) for r in svc.fetchall()]\n"
    "        ev = await db.execute(text(\n"
    "            'SELECT event_code, event_name, recipient_type, notification_services '\n"
    "            'FROM notification_events ORDER BY event_code, recipient_type'\n"
    "        ))\n"
    "        events = [dict(r._mapping) for r in ev.fetchall()]\n"
    "    print(json.dumps({'services': services, 'events': events}, default=str))\n"
    "asyncio.run(main())\n"
)


def main() -> int:
    password = os.environ.get("DEPLOY_SSH_PASSWORD")
    if not password:
        print("Set DEPLOY_SSH_PASSWORD", file=sys.stderr)
        return 1

    roots = [
        "/var/www/backend/api",
        "/var/www/staging-api",
    ]
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=password, timeout=30, allow_agent=False, look_for_keys=False)

    for root in roots:
        remote_script = f"{root}/scripts/_export_notif_fixtures_once.py"
        sftp = c.open_sftp()
        with sftp.open(remote_script, "w") as rf:
            rf.write(REMOTE_PY.encode("utf-8"))
        sftp.close()
        cmd = (
            f"bash -lc 'cd {root} && "
            f"export DATABASE_URL=$(grep -m1 ^DATABASE_URL= .env | cut -d= -f2- | tr -d \"\\r\") && "
            f"PYTHONPATH=. ./venv/bin/python scripts/_export_notif_fixtures_once.py'"
        )
        _, stdout, stderr = c.exec_command(cmd, timeout=180)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        if not out or out.startswith("Traceback"):
            print(f"--- {root} failed ---", file=sys.stderr)
            print(out[:500], err[:500], file=sys.stderr)
            continue
        data = json.loads(out)
        label = "production" if "backend/api" in root else "staging"
        os.makedirs(OUT_DIR, exist_ok=True)
        path = os.path.join(OUT_DIR, f"notification_snapshot_{label}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        filled = sum(
            1
            for s in data["services"]
            if (s.get("template_name") or "").strip()
            or (s.get("email_subject") or "").strip()
            or (s.get("email_body") or "").strip()
        )
        print(f"Wrote {path}: {len(data['services'])} services ({filled} with content), {len(data['events'])} events")
        if label == "production" and filled > 10:
            # canonical fixtures for migration
            for name in ("notification_services_content.json", "notification_events_platform_defaults.json"):
                p = os.path.join(OUT_DIR, name)
                with open(p, "w", encoding="utf-8") as f:
                    if "services" in name:
                        json.dump(data["services"], f, indent=2, default=str)
                    else:
                        json.dump(data["events"], f, indent=2, default=str)
                print(f"  -> {p}")

    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
