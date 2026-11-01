"""One-off staging admin deploy: pull + build."""
from __future__ import annotations

import re
from pathlib import Path

import paramiko

DOC = Path(__file__).resolve().parents[2] / "docs" / "notification-rebuild-prompts" / "_shared-staging-ops.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    password = re.search(r"^Password: (.+)$", text, re.MULTILINE).group(1).strip()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("187.77.185.240", username="pita-ihsir", password=password, timeout=30)

    def run(cmd: str) -> int:
        _stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        if out.strip():
            print(out)
        if err.strip():
            print(err)
        return stdout.channel.recv_exit_status()

    admin_dir = "/var/www/staging-admin-app"
    code = run(f"bash -lc 'cd {admin_dir} && git pull origin main'")
    if code != 0:
        raise SystemExit(code)
    code = run(f"bash -lc 'cd {admin_dir} && npm ci && npm run build'")
    if code != 0:
        raise SystemExit(code)
    print("STAGING_ADMIN_OK")
    client.close()


if __name__ == "__main__":
    main()
