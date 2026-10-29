"""Database access for user onboarding payload field catalog and camp rows."""

from __future__ import annotations

import secrets
import string

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from modules.engagements.models import CampUserOnboardingPayloadField, UserOnboardingPayloadField

_CAMP_CODE_LENGTH = 12
_CAMP_CODE_ALPHABET = string.ascii_letters + string.digits
_MAX_CAMP_CODE_ATTEMPTS = 32


def generate_camp_code(length: int = _CAMP_CODE_LENGTH) -> str:
    return "".join(secrets.choice(_CAMP_CODE_ALPHABET) for _ in range(length))


class UserOnboardingPayloadFieldsRepository:
    """CRUD for user_onboarding_payload_fields."""

    async def list_fields(
        self,
        db: AsyncSession,
        *,
        page: int,
        limit: int,
    ) -> list[UserOnboardingPayloadField]:
        offset = (page - 1) * limit
        result = await db.execute(
            select(UserOnboardingPayloadField)
            .order_by(UserOnboardingPayloadField.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_all(self, db: AsyncSession) -> list[UserOnboardingPayloadField]:
        result = await db.execute(
            select(UserOnboardingPayloadField).order_by(UserOnboardingPayloadField.id.asc())
        )
        return list(result.scalars().all())

    async def count_fields(self, db: AsyncSession) -> int:
        result = await db.execute(select(func.count()).select_from(UserOnboardingPayloadField))
        return int(result.scalar_one())

    async def get_by_id(self, db: AsyncSession, *, field_id: int) -> UserOnboardingPayloadField | None:
        result = await db.execute(
            select(UserOnboardingPayloadField).where(UserOnboardingPayloadField.id == field_id)
        )
        return result.scalar_one_or_none()

    async def get_by_payload_key(
        self,
        db: AsyncSession,
        *,
        payload_key: str,
    ) -> UserOnboardingPayloadField | None:
        result = await db.execute(
            select(UserOnboardingPayloadField).where(UserOnboardingPayloadField.payload_key == payload_key)
        )
        return result.scalar_one_or_none()

    async def create(self, db: AsyncSession, row: UserOnboardingPayloadField) -> UserOnboardingPayloadField:
        db.add(row)
        await db.flush()
        return row

    async def delete_by_id(self, db: AsyncSession, *, field_id: int) -> int:
        result = await db.execute(
            delete(UserOnboardingPayloadField).where(UserOnboardingPayloadField.id == field_id)
        )
        return int(result.rowcount or 0)


class CampOnboardingPayloadRepository:
    """CRUD for camp_user_onboarding_payload_fields."""

    async def get_by_camp_no(
        self,
        db: AsyncSession,
        *,
        camp_no: int,
    ) -> CampUserOnboardingPayloadField | None:
        result = await db.execute(
            select(CampUserOnboardingPayloadField).where(
                CampUserOnboardingPayloadField.camp_no == camp_no
            )
        )
        return result.scalar_one_or_none()

    async def get_by_camp_code(
        self,
        db: AsyncSession,
        *,
        camp_code: str,
    ) -> CampUserOnboardingPayloadField | None:
        result = await db.execute(
            select(CampUserOnboardingPayloadField).where(
                CampUserOnboardingPayloadField.camp_code == camp_code
            )
        )
        return result.scalar_one_or_none()

    async def _unique_camp_code(self, db: AsyncSession) -> str:
        for _ in range(_MAX_CAMP_CODE_ATTEMPTS):
            code = generate_camp_code()
            existing = await self.get_by_camp_code(db, camp_code=code)
            if existing is None:
                return code
        raise RuntimeError("Failed to generate unique camp_code")

    async def ensure_row(self, db: AsyncSession, *, camp_no: int) -> None:
        camp_code = await self._unique_camp_code(db)
        stmt = (
            insert(CampUserOnboardingPayloadField)
            .values(camp_no=camp_no, camp_code=camp_code, onboarding_payload={})
            .on_conflict_do_nothing(index_elements=["camp_no"])
        )
        await db.execute(stmt)

    async def create_initial_row(
        self,
        db: AsyncSession,
        *,
        camp_no: int,
    ) -> CampUserOnboardingPayloadField:
        camp_code = await self._unique_camp_code(db)
        row = CampUserOnboardingPayloadField(
            camp_no=camp_no,
            camp_code=camp_code,
            onboarding_payload={},
        )
        db.add(row)
        await db.flush()
        return row

    async def update_payload(
        self,
        db: AsyncSession,
        *,
        row: CampUserOnboardingPayloadField,
        onboarding_payload: dict,
    ) -> CampUserOnboardingPayloadField:
        row.onboarding_payload = onboarding_payload
        await db.flush()
        return row

    async def delete_row(self, db: AsyncSession, *, row: CampUserOnboardingPayloadField) -> None:
        await db.delete(row)
        await db.flush()

    async def remap_camp_no(
        self,
        db: AsyncSession,
        *,
        from_camp_no: int,
        to_camp_no: int,
    ) -> None:
        source = await self.get_by_camp_no(db, camp_no=from_camp_no)
        if source is None:
            return
        target = await self.get_by_camp_no(db, camp_no=to_camp_no)
        if target is None:
            source.camp_no = to_camp_no
            await db.flush()
            return
        await self.delete_row(db, row=source)
