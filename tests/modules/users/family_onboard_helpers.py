"""Shared seeds and payloads for family onboard tests."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.column_types import STATUS_ENGAGEMENT


def engagement_status_is(raw_status: object, label: str) -> bool:
    """Match engagement status from raw SQL row or ORM (int code or string label)."""
    expected = STATUS_ENGAGEMENT[label]
    if raw_status is None:
        return False
    if isinstance(raw_status, int):
        return raw_status == expected
    s = str(raw_status).strip().lower()
    if s.isdigit():
        return int(s) == expected
    return s == label


async def seed_family_onboard_gift_notification_services(test_db_session: AsyncSession) -> None:
    """Seed hardcoded family-onboard Diwali gift notification services."""
    from modules.notifications.family_onboard_gift_notify import (
        RECEIVER_EMAIL_KEY,
        RECEIVER_WHATSAPP_KEY,
        SENDER_EMAIL_KEY,
        SENDER_WHATSAPP_KEY,
    )

    for key, channel, path in (
        (SENDER_WHATSAPP_KEY, "whatsapp", "/family-onboard-sender-whatsapp-v1"),
        (SENDER_EMAIL_KEY, "email", "/family-onboard-sender-email-v1"),
        (RECEIVER_WHATSAPP_KEY, "whatsapp", "/family-onboard-receiver-whatsapp-v1"),
        (RECEIVER_EMAIL_KEY, "email", "/family-onboard-receiver-email-v1"),
    ):
        await test_db_session.execute(
            text(
                "INSERT INTO notification_services "
                "(service_key, display_name, channel, webhook_path, is_active, "
                "require_blood_report_url, require_bio_ai_report_url, require_participant_detail, "
                "require_otp, require_session_details, require_external_link) "
                "VALUES (:sk, :sk, :ch, :path, true, false, false, true, false, false, false) "
                "ON CONFLICT (service_key) DO UPDATE SET "
                "require_participant_detail = true, is_active = true"
            ),
            {"sk": key, "ch": channel, "path": path},
        )
    await test_db_session.commit()


async def seed_family_onboard_platform_defaults(test_db_session: AsyncSession) -> None:
    """Seed packages aligned with platform_settings B2C default diagnostic_package_id=6."""
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, status) "
            "VALUES (1, 'PK1', 'Package', 1) ON CONFLICT (package_id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package "
            "(diagnostic_package_id, reference_id, package_name, diagnostic_provider, status, price, external_package_code) "
            "VALUES (6, 'REF-H6', 'Healthians Package', 'healthians', 1, 500, '101') "
            "ON CONFLICT (diagnostic_package_id) DO UPDATE SET "
            "diagnostic_provider = EXCLUDED.diagnostic_provider, "
            "external_package_code = EXCLUDED.external_package_code, status = EXCLUDED.status"
        )
    )
    await test_db_session.commit()


async def seed_primary_user(
    test_db_session: AsyncSession,
    *,
    user_id: int,
    phone: str,
    email: str,
    relationship: str = "self",
    first_name: str = "Primary",
) -> None:
    await test_db_session.execute(
        text(
            "INSERT INTO users (user_id, first_name, age, phone, email, status, parent_id, relationship) "
            "VALUES (:uid, :first_name, 35, :phone, :email, 1, NULL, CAST(:relationship AS user_relationship_enum)) "
            "ON CONFLICT (user_id) DO NOTHING"
        ),
        {
            "uid": user_id,
            "first_name": first_name,
            "phone": phone,
            "email": email,
            "relationship": relationship,
        },
    )
    await test_db_session.commit()


async def seed_subprofile_user(
    test_db_session: AsyncSession,
    *,
    user_id: int,
    parent_id: int,
    phone: str,
    email: str,
    relationship: str = "child",
    first_name: str = "Sub",
) -> None:
    await test_db_session.execute(
        text(
            "INSERT INTO users (user_id, first_name, age, phone, email, status, parent_id, relationship) "
            "VALUES (:uid, :first_name, 12, :phone, :email, 1, :parent_id, "
            "CAST(:relationship AS user_relationship_enum)) "
            "ON CONFLICT (user_id) DO NOTHING"
        ),
        {
            "uid": user_id,
            "parent_id": parent_id,
            "first_name": first_name,
            "phone": phone,
            "email": email,
            "relationship": relationship,
        },
    )
    await test_db_session.commit()


def engagement_ids_from_start(start_data: dict) -> list[int]:
    """Collect engagement_id values from a family-onboard start response data object."""
    return [int(m["engagement_id"]) for m in start_data["members"]]


def family_onboard_start_payload(
    *,
    booker_phone: str = "9000100001",
    member_phone: str = "9000100002",
    second_member_phone: str | None = None,
    member_relation: str = "child",
    booker_email: str = "adi.family@example.com",
) -> dict:
    members = [
        {
            "name": "Akash Kumar",
            "phone": member_phone,
            "relation": member_relation,
            "age": 28,
            "gender": "Male",
            "blood_collection_date": "2026-03-15",
            "blood_collection_time_slot": "10:00",
        }
    ]
    if second_member_phone:
        members.append(
            {
                "name": "Riya Kumar",
                "phone": second_member_phone,
                "relation": "spouse",
                "age": 26,
                "gender": "Female",
                "blood_collection_date": "2026-03-15",
                "blood_collection_time_slot": "11:00",
            }
        )
    return {
        "booker": {
            "name": "Adi Kumar",
            "phone": booker_phone,
            "email": booker_email,
        },
        "members": members,
    }
