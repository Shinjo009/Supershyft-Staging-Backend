"""Shim entrypoint → ``db.jobs.backfill_report_sent``."""

from dotenv import load_dotenv

from db.jobs.backfill_report_sent.command import main

if __name__ == "__main__":
    load_dotenv(override=False)
    raise SystemExit(main())
