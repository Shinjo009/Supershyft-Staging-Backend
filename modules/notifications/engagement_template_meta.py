"""Load engagement fields into notification template context."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.experts.consultations import format_consultation_types_list
from modules.experts.repository import ExpertTypesRepository


async def load_engagement_template_meta(
    db: AsyncSession,
    engagement_id: int,
) -> dict[str, str] | None:
    from modules.engagements.models import Engagement

    engagement_row = await db.get(Engagement, engagement_id)
    if engagement_row is None:
        return None

    types = await ExpertTypesRepository().list_all(db)
    type_keys_order = [t.type_key for t in types]
    consultations = engagement_row.consultations if isinstance(engagement_row.consultations, dict) else {}

    return {
        "engagement_id": str(engagement_row.engagement_id),
        "engagement_code": str(engagement_row.engagement_code or "").strip(),
        "engagement_name": str(engagement_row.engagement_name or "").strip(),
        "consultation_types": format_consultation_types_list(
            consultations,
            type_keys_order=type_keys_order,
        ),
    }


def merge_engagement_member_block(
    engagement_meta: dict[str, str],
    contact_engagement: object | None,
) -> dict[str, str]:
    merged = dict(engagement_meta)
    if isinstance(contact_engagement, dict):
        for key, value in contact_engagement.items():
            if value not in (None, ""):
                merged[str(key)] = str(value).strip()
    return merged