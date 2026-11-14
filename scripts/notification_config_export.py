"""Export notification configuration from current DB (staging). No PII / no notification log rows.

  export DATABASE_URL=...
  python scripts/notification_config_export.py -o /tmp/notif_config_export.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, UUID):
        return str(obj)
    return str(obj)


async def _run(out_path: Path) -> None:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise SystemExit("DATABASE_URL required")
    engine = create_async_engine(url)
    payload: dict = {"exported_at": datetime.utcnow().isoformat() + "Z", "tables": {}}
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT id, event_code, event_name, recipient_type, delivery_channel,
                           notification_services, engagement_type_id, recipient_config,
                           condition_key, emit_condition
                    FROM notification_events
                    ORDER BY id
                    """
                )
            )
        ).mappings().all()
        payload["tables"]["notification_events"] = [dict(r) for r in rows]

        rows = (
            await conn.execute(
                text(
                    """
                    SELECT notification_service_id, service_key, display_name, channel, is_active,
                           template_name, template_variables, email_subject, email_body, email_html,
                           webhook_path, require_blood_report_url, require_bio_ai_report_url,
                           require_participant_detail, require_otp, require_session_details,
                           require_external_link, created_at
                    FROM notification_services
                    ORDER BY service_key
                    """
                )
            )
        ).mappings().all()
        payload["tables"]["notification_services"] = [dict(r) for r in rows]

        rows = (
            await conn.execute(
                text(
                    """
                    SELECT en.id, en.engagement_id, e.engagement_code, en.event_code, en.event_name,
                           en.recipient_type, en.delivery_channel, en.notification_services,
                           en.recipient_config, en.condition_key, en.emit_condition,
                           en.source_binding_id, ne.event_code AS source_event_code,
                           ne.recipient_type AS source_recipient_type,
                           ne.engagement_type_id AS source_engagement_type_id,
                           ne.condition_key AS source_condition_key,
                           ne.delivery_channel AS source_delivery_channel
                    FROM engagement_notifications en
                    JOIN engagements e ON e.engagement_id = en.engagement_id
                    LEFT JOIN notification_events ne ON ne.id = en.source_binding_id
                    ORDER BY en.id
                    """
                )
            )
        ).mappings().all()
        payload["tables"]["engagement_notifications"] = [dict(r) for r in rows]

    out_path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    print(json.dumps({"ok": True, "path": str(out_path), "counts": {k: len(v) for k, v in payload["tables"].items()}}, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Export notification config JSON")
    parser.add_argument("-o", "--output", required=True, help="Output JSON path")
    args = parser.parse_args()
    import asyncio

    asyncio.run(_run(Path(args.output)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())