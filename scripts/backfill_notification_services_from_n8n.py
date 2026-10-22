"""Regenerate db/fixtures/notification_services_content.json from n8n workflows (git e543900)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    scripts = [
        ROOT / "scripts" / "generate_notification_fixtures_from_n8n.py",
        ROOT / "scripts" / "generate_notification_events_fixture.py",
    ]
    for script in scripts:
        rc = subprocess.call([sys.executable, str(script)], cwd=ROOT, env={**dict(__import__("os").environ), "PYTHONPATH": str(ROOT)})
        if rc != 0:
            return rc
    print("Fixtures updated. Run: alembic upgrade head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
