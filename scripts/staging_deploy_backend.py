"""Staging backend deploy (pull, migrate, restart)."""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import paramiko

DOC = Path(__file__).resolve().parents[2] / "docs" / "notification-rebuild-prompts" / "_shared-staging-ops.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    match = re.search(r"^Password: (.+)$", text, re.MULTILINE)
    if not match:
        raise SystemExit("Missing SSH password in shared ops doc")
    password = match.group(1).strip()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("187.77.185.240", username="pita-ihsir", password=password, timeout=30)

    def run(cmd: str) -> tuple[int, str, str]:
        _stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        return stdout.channel.recv_exit_status(), out, err

    def sudo(cmd: str) -> int:
        si, so, _se = client.exec_command(f"sudo -S {cmd}", get_pty=True)
        si.write(password + "\n")
        si.flush()
        si.channel.shutdown_write()
        out = so.read().decode(errors="replace")
        code = so.channel.recv_exit_status()
        if out.strip():
            print(out)
        return code

    try:
        code, out, err = run("cd /var/www/staging-api && git pull origin main")
        if code != 0:
            print(err, file=sys.stderr)
            raise SystemExit(code)
        code, out, err = run("bash /var/www/staging-api/scripts/staging-post-deploy.sh")
        if code != 0:
            print(err, file=sys.stderr)
            raise SystemExit(code)

        # Orphan uvicorn on 8102 blocked systemd restarts in prior deploys.
        run("fuser -k 8102/tcp 2>/dev/null || true")
        time.sleep(2)
        if sudo("systemctl restart staging-api.service") != 0:
            raise SystemExit(1)
        time.sleep(5)

        code, out, _ = run("systemctl is-active staging-api.service")
        print("service:", out.strip())
        code, out, _ = run("curl -s http://127.0.0.1:8102/health")
        print("health:", out.strip())
        code, out, _ = run("curl -s 'http://127.0.0.1:8102/webhooks/whatapi?challenge=ok'")
        print("whatapi challenge:", out.strip())
        if "ok" not in out and code != 0:
            raise SystemExit("whatapi webhook check failed")
        print("STAGING_BACKEND_OK")
    finally:
        client.close()


if __name__ == "__main__":
    main()
