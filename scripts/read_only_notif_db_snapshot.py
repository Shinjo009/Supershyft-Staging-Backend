"""Read-only notification schema/counts snapshot. Usage: source .env && python scripts/read_only_notif_db_snapshot.py"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

TABLES = (
    "notification_events",
    "notification_services",
    "engagement_notifications",
    "notifications",
    "integration_providers",
    "integration_sync_logs",
)


async def main() -> None:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    engine = create_async_engine(url)
    out: dict = {"counts": {}, "columns": {}, "samples": {}}
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        out["alembic"] = (
            await conn.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one_or_none()
        for table in TABLES:
            try:
                out["counts"][table] = int(
                    (await conn.execute(text(f"SELECT COUNT(*)::bigint FROM {table}"))).scalar_one()
                )
                cols = (
                    await conn.execute(
                        text(
                            """
                            SELECT column_name, data_type
                            FROM information_schema.columns
                            WHERE table_schema = 'public' AND table_name = :t
                            ORDER BY ordinal_position
                            """
                        ),
                        {"t": table},
                    )
                ).all()
                out["columns"][table] = [f"{r[0]}:{r[1]}" for r in cols]
            except Exception as exc:
                out["counts"][table] = f"error:{str(exc)[:120]}"
        for q, key in (
            (
                "SELECT event_code, COUNT(*)::int AS c FROM notification_events GROUP BY 1 ORDER BY 1",
                "notification_events_by_code",
            ),
            (
                "SELECT service_key, channel, is_active FROM notification_services ORDER BY service_key",
                "notification_services_list",
            ),
        ):
            try:
                rows = (await conn.execute(text(q))).mappings().all()
                out["samples"][key] = [dict(r) for r in rows[:200]]
            except Exception as exc:
                out["samples"][key] = f"error:{str(exc)[:120]}"

        legacy = (
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name LIKE '%notif%' ORDER BY 1"
        )
        out["notif_tables"] = [r[0] for r in (await conn.execute(text(legacy))).all()]
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())