"""Entry point: python -m db.jobs.backfill_users_created_at_from_metsights"""

from dotenv import load_dotenv

from db.jobs.backfill_users_created_at_from_metsights.command import main

if __name__ == "__main__":
    load_dotenv(override=False)
    raise SystemExit(main())