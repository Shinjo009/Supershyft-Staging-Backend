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


def family_onboard_start_payload(
    *,
    booker_phone: str = "9000100001",
    member_phone: str = "9000100002",
    second_member_phone: str | None = None,
) -> dict:
    members = [
        {
            "name": "Akash Kumar",
            "phone": member_phone,
            "relation": "child",
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
            "email": "adi.family@example.com",
        },
        "members": members,
    }
