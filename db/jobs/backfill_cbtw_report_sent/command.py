"""Shim: prefer ``python -m db.jobs.backfill_report_sent``.

Kept so older instructions still work. Defaults to all cohorts (16/72/73).
"""

from __future__ import annotations

from db.jobs.backfill_report_sent.command import main

if __name__ == "__main__":
    raise SystemExit(main())
