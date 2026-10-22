"""Link a blog writer to one authors row via authors.partner_id."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.blog.models import Author
from modules.employee.models import Employee
from modules.partners.models import Partner
from modules.partners.role_utils import partner_role_value


async def ensure_author_profile(db: AsyncSession, partner: Partner) -> Author | None:
    """Create the author row when the partner role is author.

    Existing rows are kept if the partner later changes role. Returns the row
    only for author partners. Reuses a row if an admin already stored the same id.
    """

    existing = await db.execute(select(Author).where(Author.partner_id == partner.partner_id))
    row = existing.scalar_one_or_none()
    if partner_role_value(partner.role) != "author":
        return row

    if row is not None:
        return row

    created = Author(partner_id=partner.partner_id)
    db.add(created)
    await db.flush()
    return created


async def ensure_employee_author(db: AsyncSession, employee: Employee) -> Author:
    """Find or create an authors row whose partner_id is the employee id."""

    existing = await db.execute(select(Author).where(Author.partner_id == employee.employee_id))
    row = existing.scalar_one_or_none()
    if row is not None:
        return row

    created = Author(partner_id=employee.employee_id)
    db.add(created)
    await db.flush()
    return created
