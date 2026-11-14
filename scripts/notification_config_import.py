"""Import notification configuration JSON into production (config tables only).

  NOTIFICATION_OUTBOUND_DISABLED=true recommended on API before traffic.

  python scripts/notification_config_import.py --input /tmp/notif_config_export.json --yes
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.asyncio import async_sessionmaker


def _binding_key(row: dict) -> tuple:
    return (
        str(row.get("event_code") or ""),
        str(row.get("recipient_type") or ""),
        row.get("engagement_type_id"),
        str(row.get("delivery_channel") or ""),
        str(row.get("condition_key") or "default"),
    )


def _slot_key(engagement_id: int, row: dict) -> tuple:
    return (
        engagement_id,
        str(row.get("event_code") or ""),
        str(row.get("recipient_type") or ""),
        str(row.get("delivery_channel") or ""),
        str(row.get("condition_key") or "default"),
    )


async def _run(input_path: Path, *, yes: bool) -> None:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise SystemExit("DATABASE_URL required")
    data = json.loads(input_path.read_text(encoding="utf-8"))
    tables = data.get("tables") or {}
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    stats = {
        "services_upserted": 0,
        "events_upserted": 0,
        "engagements_skipped_unknown_code": 0,
        "engagements_upserted": 0,
    }

    if not yes:
        print(json.dumps({"dry_run": True, "counts_in_file": {k: len(v) for k, v in tables.items()}}, indent=2))
        return

    async with factory() as db:
        staging_id_to_natural: dict[int, tuple] = {}
        for row in tables.get("notification_events") or []:
            sid = row.get("id")
            if sid is not None:
                staging_id_to_natural[int(sid)] = _binding_key(row)

        prod_id_by_natural: dict[tuple, int] = {}

        for row in tables.get("notification_services") or []:
            sk = str(row.get("service_key") or "").strip()
            if not sk:
                continue
            await db.execute(
                text(
                    """
                    INSERT INTO notification_services (
                        service_key, display_name, channel, is_active, template_name, template_variables,
                        email_subject, email_body, email_html, webhook_path,
                        require_blood_report_url, require_bio_ai_report_url, require_participant_detail,
                        require_otp, require_session_details, require_external_link
                    ) VALUES (
                        :service_key, :display_name, :channel, :is_active, :template_name, CAST(:template_variables AS jsonb),
                        :email_subject, :email_body, :email_html, :webhook_path,
                        :require_blood, :require_bioai, :require_participant, :require_otp,
                        :require_session, :require_external
                    )
                    ON CONFLICT (service_key) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        channel = EXCLUDED.channel,
                        is_active = EXCLUDED.is_active,
                        template_name = EXCLUDED.template_name,
                        template_variables = EXCLUDED.template_variables,
                        email_subject = EXCLUDED.email_subject,
                        email_body = EXCLUDED.email_body,
                        email_html = EXCLUDED.email_html,
                        webhook_path = EXCLUDED.webhook_path,
                        require_blood_report_url = EXCLUDED.require_blood_report_url,
                        require_bio_ai_report_url = EXCLUDED.require_bio_ai_report_url,
                        require_participant_detail = EXCLUDED.require_participant_detail,
                        require_otp = EXCLUDED.require_otp,
                        require_session_details = EXCLUDED.require_session_details,
                        require_external_link = EXCLUDED.require_external_link
                    """
                ),
                {
                    "service_key": sk,
                    "display_name": row.get("display_name"),
                    "channel": row.get("channel"),
                    "is_active": row.get("is_active", True),
                    "template_name": row.get("template_name"),
                    "template_variables": json.dumps(row.get("template_variables") or []),
                    "email_subject": row.get("email_subject"),
                    "email_body": row.get("email_body"),
                    "email_html": row.get("email_html"),
                    "webhook_path": row.get("webhook_path"),
                    "require_blood": row.get("require_blood_report_url", False),
                    "require_bioai": row.get("require_bio_ai_report_url", False),
                    "require_participant": row.get("require_participant_detail", False),
                    "require_otp": row.get("require_otp", False),
                    "require_session": row.get("require_session_details", False),
                    "require_external": row.get("require_external_link", False),
                },
            )
            stats["services_upserted"] += 1

        for row in tables.get("notification_events") or []:
            key = _binding_key(row)
            existing = (
                await db.execute(
                    text(
                        """
                        SELECT id FROM notification_events
                        WHERE event_code = :event_code AND recipient_type = :recipient_type
                          AND engagement_type_id IS NOT DISTINCT FROM :etype
                          AND delivery_channel = :delivery_channel
                          AND condition_key = :condition_key
                        LIMIT 1
                        """
                    ),
                    {
                        "event_code": key[0],
                        "recipient_type": key[1],
                        "etype": key[2],
                        "delivery_channel": key[3],
                        "condition_key": key[4],
                    },
                )
            ).scalar_one_or_none()
            params = {
                "event_code": row.get("event_code"),
                "event_name": row.get("event_name"),
                "recipient_type": row.get("recipient_type"),
                "delivery_channel": row.get("delivery_channel"),
                "notification_services": json.dumps(row.get("notification_services") or []),
                "engagement_type_id": row.get("engagement_type_id"),
                "recipient_config": json.dumps(row.get("recipient_config")) if row.get("recipient_config") else None,
                "condition_key": row.get("condition_key") or "default",
                "emit_condition": json.dumps(row.get("emit_condition")) if row.get("emit_condition") else None,
            }
            if existing:
                await db.execute(
                    text(
                        """
                        UPDATE notification_events SET
                            event_name = :event_name,
                            notification_services = CAST(:notification_services AS jsonb),
                            recipient_config = CAST(:recipient_config AS jsonb),
                            emit_condition = CAST(:emit_condition AS jsonb)
                        WHERE id = :id
                        """
                    ),
                    {**params, "id": int(existing)},
                )
                prod_id_by_natural[key] = int(existing)
            else:
                new_id = (
                    await db.execute(
                        text(
                            """
                            INSERT INTO notification_events (
                                event_code, event_name, recipient_type, delivery_channel,
                                notification_services, engagement_type_id, recipient_config,
                                condition_key, emit_condition
                            ) VALUES (
                                :event_code, :event_name, :recipient_type, :delivery_channel,
                                CAST(:notification_services AS jsonb), :engagement_type_id,
                                CAST(:recipient_config AS jsonb), :condition_key,
                                CAST(:emit_condition AS jsonb)
                            )
                            RETURNING id
                            """
                        ),
                        params,
                    )
                ).scalar_one()
                prod_id_by_natural[key] = int(new_id)
            stats["events_upserted"] += 1

        code_to_eng = {
            str(r[0]): int(r[1])
            for r in (
                await db.execute(text("SELECT engagement_code, engagement_id FROM engagements WHERE engagement_code IS NOT NULL"))
            ).all()
        }

        for row in tables.get("engagement_notifications") or []:
            code = str(row.get("engagement_code") or "").strip()
            prod_eid = code_to_eng.get(code)
            if prod_eid is None:
                stats["engagements_skipped_unknown_code"] += 1
                continue
            source_binding_id = None
            staging_src = row.get("source_binding_id")
            if staging_src is not None:
                natural = staging_id_to_natural.get(int(staging_src))
                if natural:
                    source_binding_id = prod_id_by_natural.get(natural)
            slot = _slot_key(prod_eid, row)
            await db.execute(
                text(
                    """
                    INSERT INTO engagement_notifications (
                        engagement_id, event_code, event_name, recipient_type, delivery_channel,
                        notification_services, recipient_config, condition_key, emit_condition,
                        source_binding_id
                    ) VALUES (
                        :engagement_id, :event_code, :event_name, :recipient_type, :delivery_channel,
                        CAST(:notification_services AS jsonb),
                        CAST(:recipient_config AS jsonb), :condition_key,
                        CAST(:emit_condition AS jsonb), :source_binding_id
                    )
                    ON CONFLICT ON CONSTRAINT uq_engagement_notification_slot DO UPDATE SET
                        event_name = EXCLUDED.event_name,
                        notification_services = EXCLUDED.notification_services,
                        recipient_config = EXCLUDED.recipient_config,
                        emit_condition = EXCLUDED.emit_condition,
                        source_binding_id = EXCLUDED.source_binding_id
                    """
                ),
                {
                    "engagement_id": prod_eid,
                    "event_code": row.get("event_code"),
                    "event_name": row.get("event_name"),
                    "recipient_type": row.get("recipient_type") or "user",
                    "delivery_channel": row.get("delivery_channel") or "whatsapp",
                    "notification_services": json.dumps(row.get("notification_services") or []),
                    "recipient_config": json.dumps(row.get("recipient_config")) if row.get("recipient_config") else None,
                    "condition_key": row.get("condition_key") or "default",
                    "emit_condition": json.dumps(row.get("emit_condition")) if row.get("emit_condition") else None,
                    "source_binding_id": source_binding_id,
                },
            )
            stats["engagements_upserted"] += 1

        await db.commit()
    print(json.dumps({"ok": True, "stats": stats}, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Import notification config JSON")
    parser.add_argument("--input", required=True)
    parser.add_argument("--yes", action="store_true", help="Execute writes (required)")
    args = parser.parse_args()
    import asyncio

    asyncio.run(_run(Path(args.input), yes=args.yes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())