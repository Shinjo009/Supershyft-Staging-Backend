"""Data access for participant_blood_bookings."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from modules.engagements.blood_booking_enums import BloodBookingRelation, BloodBookingStatus
from modules.engagements.models import Engagement, EngagementParticipant, ParticipantBloodBooking


def current_blood_booking_subquery():
    """One current collection row per engagement_participant_id (PostgreSQL DISTINCT ON)."""
    return (
        select(ParticipantBloodBooking)
        .distinct(ParticipantBloodBooking.engagement_participant_id)
        .where(ParticipantBloodBooking.status == BloodBookingStatus.active.value)
        .where(ParticipantBloodBooking.relation != BloodBookingRelation.resample.value)
        .order_by(
            ParticipantBloodBooking.engagement_participant_id,
            ParticipantBloodBooking.collected_at.desc().nullslast(),
            ParticipantBloodBooking.id.desc(),
        )
    ).subquery("curr_pbb")


def _relation_value(relation: BloodBookingRelation | str) -> str:
    return relation.value if isinstance(relation, BloodBookingRelation) else str(relation)


def _status_value(status: BloodBookingStatus | str) -> str:
    return status.value if isinstance(status, BloodBookingStatus) else str(status)


class BloodBookingsRepository:
    async def get_by_id(
        self,
        db: AsyncSession,
        *,
        blood_booking_id: int,
    ) -> ParticipantBloodBooking | None:
        result = await db.execute(
            select(ParticipantBloodBooking).where(ParticipantBloodBooking.id == blood_booking_id)
        )
        return result.scalar_one_or_none()

    async def get_by_booking_id(
        self,
        db: AsyncSession,
        *,
        booking_id: str,
    ) -> ParticipantBloodBooking | None:
        bid = (booking_id or "").strip()
        if not bid:
            return None
        result = await db.execute(
            select(ParticipantBloodBooking)
            .where(ParticipantBloodBooking.booking_id == bid)
            .order_by(ParticipantBloodBooking.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_active_by_booking_id(
        self,
        db: AsyncSession,
        *,
        booking_id: str,
    ) -> ParticipantBloodBooking | None:
        bid = (booking_id or "").strip()
        if not bid:
            return None
        result = await db.execute(
            select(ParticipantBloodBooking)
            .where(ParticipantBloodBooking.booking_id == bid)
            .where(ParticipantBloodBooking.status == BloodBookingStatus.active.value)
            .order_by(ParticipantBloodBooking.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_for_participant(
        self,
        db: AsyncSession,
        *,
        engagement_participant_id: int,
    ) -> list[ParticipantBloodBooking]:
        result = await db.execute(
            select(ParticipantBloodBooking)
            .where(ParticipantBloodBooking.engagement_participant_id == engagement_participant_id)
            .order_by(ParticipantBloodBooking.id.desc())
        )
        return list(result.scalars().all())

    async def get_current_collection(
        self,
        db: AsyncSession,
        *,
        engagement_participant_id: int,
    ) -> ParticipantBloodBooking | None:
        """Active row that is not a resample; latest by collected_at then id."""
        result = await db.execute(
            select(ParticipantBloodBooking)
            .where(ParticipantBloodBooking.engagement_participant_id == engagement_participant_id)
            .where(ParticipantBloodBooking.status == BloodBookingStatus.active.value)
            .where(ParticipantBloodBooking.relation != BloodBookingRelation.resample.value)
            .order_by(
                ParticipantBloodBooking.collected_at.desc().nullslast(),
                ParticipantBloodBooking.id.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_or_create_current_collection(
        self,
        db: AsyncSession,
        *,
        engagement_participant_id: int,
        relation: BloodBookingRelation = BloodBookingRelation.primary,
    ) -> ParticipantBloodBooking:
        current = await self.get_current_collection(db, engagement_participant_id=engagement_participant_id)
        if current is not None:
            return current
        row = ParticipantBloodBooking(
            engagement_participant_id=engagement_participant_id,
            relation=_relation_value(relation),
            status=BloodBookingStatus.active.value,
        )
        db.add(row)
        await db.flush()
        return row

    async def has_active_booking_id(
        self,
        db: AsyncSession,
        *,
        engagement_participant_id: int,
    ) -> bool:
        current = await self.get_current_collection(db, engagement_participant_id=engagement_participant_id)
        if current is None:
            return False
        return bool((current.booking_id or "").strip())

    async def get_report_root(
        self,
        db: AsyncSession,
        *,
        collection_row: ParticipantBloodBooking,
    ) -> ParticipantBloodBooking:
        """Root row that holds lab/PDF for this collection's report group."""
        rel = _relation_value(collection_row.relation)
        if rel == BloodBookingRelation.resample.value:
            parent_id = (collection_row.parent_booking_id or "").strip()
            if parent_id:
                parent = await self.get_by_booking_id(db, booking_id=parent_id)
                if parent is not None:
                    return await self.get_report_root(db, collection_row=parent)
        return collection_row

    async def list_resample_children(
        self,
        db: AsyncSession,
        *,
        root: ParticipantBloodBooking,
    ) -> list[ParticipantBloodBooking]:
        root_bid = (root.booking_id or "").strip()
        if not root_bid:
            return []
        result = await db.execute(
            select(ParticipantBloodBooking)
            .where(ParticipantBloodBooking.engagement_participant_id == root.engagement_participant_id)
            .where(ParticipantBloodBooking.relation == BloodBookingRelation.resample.value)
            .where(ParticipantBloodBooking.status == BloodBookingStatus.active.value)
            .where(ParticipantBloodBooking.parent_booking_id == root_bid)
        )
        return list(result.scalars().all())

    async def list_active_report_groups(
        self,
        db: AsyncSession,
        *,
        engagement_participant_id: int,
    ) -> list[ParticipantBloodBooking]:
        """One root per active primary/redraw/reschedule chain (not resample)."""
        result = await db.execute(
            select(ParticipantBloodBooking)
            .where(ParticipantBloodBooking.engagement_participant_id == engagement_participant_id)
            .where(ParticipantBloodBooking.status == BloodBookingStatus.active.value)
            .where(ParticipantBloodBooking.relation != BloodBookingRelation.resample.value)
            .order_by(ParticipantBloodBooking.id.asc())
        )
        return list(result.scalars().all())

    async def count_cabin_slot_participants(
        self,
        db: AsyncSession,
        *,
        engagement_id: int,
        blood_collection_cabin: str,
        engagement_date: date,
        slot_start_time: time,
        slot_detail_id: int | None = None,
        exclude_engagement_participant_id: int | None = None,
    ) -> int:
        query = (
            select(func.count())
            .select_from(ParticipantBloodBooking)
            .join(
                EngagementParticipant,
                EngagementParticipant.engagement_participant_id
                == ParticipantBloodBooking.engagement_participant_id,
            )
            .where(ParticipantBloodBooking.collection_cabin == blood_collection_cabin)
            .where(ParticipantBloodBooking.collection_date == engagement_date)
            .where(ParticipantBloodBooking.collection_time == slot_start_time)
            .where(ParticipantBloodBooking.status == BloodBookingStatus.active.value)
        )
        if exclude_engagement_participant_id is not None:
            query = query.where(
                ParticipantBloodBooking.engagement_participant_id != exclude_engagement_participant_id
            )
        if slot_detail_id is not None:
            query = query.join(
                Engagement,
                Engagement.engagement_id == EngagementParticipant.engagement_id,
            ).where(Engagement.slot_detail_id == slot_detail_id)
        else:
            query = query.where(EngagementParticipant.engagement_id == engagement_id)
        result = await db.execute(query)
        return int(result.scalar_one())

    async def list_cabin_slot_occupancy(
        self,
        db: AsyncSession,
        *,
        engagement_id: int,
        slot_detail_id: int | None = None,
    ) -> list[tuple]:
        query = (
            select(
                ParticipantBloodBooking.collection_cabin,
                ParticipantBloodBooking.collection_date,
                ParticipantBloodBooking.collection_time,
                func.count(),
            )
            .join(
                EngagementParticipant,
                EngagementParticipant.engagement_participant_id
                == ParticipantBloodBooking.engagement_participant_id,
            )
            .where(ParticipantBloodBooking.collection_cabin.isnot(None))
            .where(ParticipantBloodBooking.collection_date.isnot(None))
            .where(ParticipantBloodBooking.collection_time.isnot(None))
            .where(ParticipantBloodBooking.status == BloodBookingStatus.active.value)
        )
        if slot_detail_id is not None:
            query = query.join(
                Engagement,
                Engagement.engagement_id == EngagementParticipant.engagement_id,
            ).where(Engagement.slot_detail_id == slot_detail_id)
        else:
            query = query.where(EngagementParticipant.engagement_id == engagement_id)
        query = query.group_by(
            ParticipantBloodBooking.collection_cabin,
            ParticipantBloodBooking.collection_date,
            ParticipantBloodBooking.collection_time,
        )
        result = await db.execute(query)
        return list(result.all())

    async def clear_healthians_booking_on_row(
        self,
        db: AsyncSession,
        *,
        row: ParticipantBloodBooking,
    ) -> None:
        row.booking_id = None
        row.barcode = None
        row.status = BloodBookingStatus.cancelled.value
        db.add(row)
        await db.flush()

    async def record_reschedule(
        self,
        db: AsyncSession,
        *,
        current: ParticipantBloodBooking,
        new_booking_id: str,
        collection_date: date | None = None,
        collection_time: time | None = None,
        collection_time_slot_id: str | None = None,
    ) -> ParticipantBloodBooking:
        old_bid = (current.booking_id or "").strip()
        current.status = BloodBookingStatus.superseded.value
        db.add(current)

        new_row = ParticipantBloodBooking(
            engagement_participant_id=current.engagement_participant_id,
            collection_date=collection_date if collection_date is not None else current.collection_date,
            collection_cabin=current.collection_cabin,
            collection_time=collection_time if collection_time is not None else current.collection_time,
            collection_time_slot_id=(
                collection_time_slot_id
                if collection_time_slot_id is not None
                else current.collection_time_slot_id
            ),
            booking_id=new_booking_id,
            barcode=current.barcode if (current.barcode or "").strip() != old_bid else new_booking_id,
            relation=BloodBookingRelation.reschedule.value,
            parent_booking_id=old_bid or None,
            status=BloodBookingStatus.active.value,
            diagnostic_report_url=current.diagnostic_report_url,
            blood_parameters=current.blood_parameters,
            blood_report_raw=current.blood_report_raw,
            blood_parameters_full_report=current.blood_parameters_full_report,
            blood_parameters_verified_at=current.blood_parameters_verified_at,
        )
        db.add(new_row)
        await db.flush()
        return new_row

    async def insert_resample(
        self,
        db: AsyncSession,
        *,
        engagement_participant_id: int,
        booking_id: str,
        parent_booking_id: str,
        barcode: str | None = None,
    ) -> ParticipantBloodBooking:
        parent = await self.get_by_booking_id(db, booking_id=parent_booking_id)
        row = ParticipantBloodBooking(
            engagement_participant_id=engagement_participant_id,
            collection_date=parent.collection_date if parent else None,
            collection_cabin=parent.collection_cabin if parent else None,
            collection_time=parent.collection_time if parent else None,
            collection_time_slot_id=parent.collection_time_slot_id if parent else None,
            booking_id=booking_id,
            barcode=barcode,
            relation=BloodBookingRelation.resample.value,
            parent_booking_id=parent_booking_id,
            status=BloodBookingStatus.active.value,
        )
        db.add(row)
        await db.flush()
        return row

    async def insert_redraw(
        self,
        db: AsyncSession,
        *,
        engagement_participant_id: int,
        barcode: str,
    ) -> ParticipantBloodBooking:
        current = await self.get_current_collection(db, engagement_participant_id=engagement_participant_id)
        row = ParticipantBloodBooking(
            engagement_participant_id=engagement_participant_id,
            collection_date=current.collection_date if current else None,
            collection_cabin=current.collection_cabin if current else None,
            collection_time=current.collection_time if current else None,
            collection_time_slot_id=current.collection_time_slot_id if current else None,
            barcode=barcode,
            relation=BloodBookingRelation.redraw.value,
            status=BloodBookingStatus.active.value,
        )
        db.add(row)
        await db.flush()
        return row


def blood_booking_to_participant_fields(row: ParticipantBloodBooking | None) -> dict[str, Any]:
    """Map current collection row to legacy participant API field names."""
    if row is None:
        return {
            "engagement_date": None,
            "slot_start_time": None,
            "blood_collection_cabin": None,
            "blood_collection_time_slot_id": None,
            "barcode": None,
            "booking_id": None,
        }
    slot = row.collection_time
    return {
        "engagement_date": row.collection_date.isoformat() if row.collection_date else None,
        "slot_start_time": slot.isoformat() if slot is not None else None,
        "blood_collection_cabin": row.collection_cabin,
        "blood_collection_time_slot_id": row.collection_time_slot_id,
        "barcode": row.barcode,
        "booking_id": row.booking_id,
    }


def blood_bookings_to_api_list(rows: list[ParticipantBloodBooking]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        rel = row.relation
        rel_str = rel.value if hasattr(rel, "value") else str(rel)
        st = row.status
        st_str = st.value if hasattr(st, "value") else str(st)
        slot = row.collection_time
        out.append(
            {
                "id": row.id,
                "booking_id": row.booking_id,
                "barcode": row.barcode,
                "collection_date": row.collection_date.isoformat() if row.collection_date else None,
                "collection_time": slot.isoformat() if slot is not None else None,
                "collection_cabin": row.collection_cabin,
                "collection_time_slot_id": row.collection_time_slot_id,
                "collected_at": row.collected_at.isoformat() if row.collected_at else None,
                "relation": rel_str,
                "parent_booking_id": row.parent_booking_id,
                "status": st_str,
                "diagnostic_report_url": row.diagnostic_report_url,
                "has_blood_parameters": row.blood_parameters is not None,
            }
        )
    return out
