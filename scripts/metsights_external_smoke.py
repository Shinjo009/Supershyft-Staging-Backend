"""Smoke-test MetSights External API paths (profiles, record, report metadata).

Run from dev-api with .env loaded:
  python scripts/metsights_external_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date

from dotenv import load_dotenv

# Allow running as script from repo root or dev-api/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import settings
from modules.metsights.client import MetsightsClient, _metsights_url


async def main() -> int:
    load_dotenv()
    if not settings.METSIGHTS_API_KEY:
        print("METSIGHTS_API_KEY missing — skip smoke test")
        return 1

    client = MetsightsClient()
    dob = date(1990, 1, 15).isoformat()
    print("URL builder:", _metsights_url("profiles"))

    created = await client.create_profile(data={"gender": "1", "date_of_birth": dob})
    profile_id = str((created.get("data") or {}).get("id") or "").strip()
    if not profile_id:
        print("FAIL: profile create returned no id", created)
        return 1
    print("OK profile", profile_id)

    sub_pro = "01975457-778f-064b-78a5-6990afec7881"
    record = await client.create_profile_record(
        profile_id=profile_id,
        data={"subscription_id": sub_pro},
    )
    record_id = str((record.get("data") or {}).get("id") or "").strip()
    if not record_id:
        print("FAIL: record create", record)
        return 1
    print("OK record", record_id)

    detail = await client.get_record_detail(record_id=record_id)
    sub = (detail.get("data") or {}).get("subscription") or {}
    print("OK record detail subscription", sub.get("id"))

    sub_fitprint = "01975457-d2fb-54af-8795-55933c580979"
    try:
        fp_record = await client.create_profile_record(
            profile_id=profile_id,
            data={"subscription_id": sub_fitprint},
        )
        fp_id = str((fp_record.get("data") or {}).get("id") or "").strip()
        if fp_id:
            print("OK fitprint record", fp_id)
        else:
            print("WARN fitprint record create:", fp_record)
    except Exception as exc:
        print("WARN fitprint record create failed:", exc)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
