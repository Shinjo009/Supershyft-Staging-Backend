"""Link a partner with role author to one authors row."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.blog.models import Author
from modules.employee.models import Employee
from modules.partners.models import Partner
from modules.partners.role_utils import partner_role_value


async def ensure_author_profile(db: AsyncSession, partner: Partner) -> Author | None:
    """Create the author byline row when the partner role is author.

    Existing rows are kept if the partner later changes role. Returns the row
    only for author partners.
    """

    existing = await db.execute(select(Author).where(Author.partner_id == partner.partner_id))
    row = existing.scalar_one_or_none()
    if partner_role_value(partner.role) != "author":
        return row

    if row is not None:
        return row

    base = (partner.name or "Author").strip()[:140] or "Author"
    name = base
    taken = await db.execute(select(Author.id).where(Author.author_name == name))
    if taken.scalar_one_or_none() is not None:
        suffix = f" {partner.partner_id}"
        name = f"{base[: 150 - len(suffix)]}{suffix}"

    created = Author(partner_id=partner.partner_id, author_name=name)
    db.add(created)
    await db.flush()
    return created


async def ensure_employee_author(db: AsyncSession, employee: Employee) -> Author:
    """Create the byline row for an admin employee. One row per employee."""

    existing = await db.execute(select(Author).where(Author.employee_id == employee.employee_id))
    row = existing.scalar_one_or_none()
    if row is not None:
        return row

    base = (employee.name or "Admin").strip()[:140] or "Admin"
    name = base
    taken = await db.execute(select(Author.id).where(Author.author_name == name))
    if taken.scalar_one_or_none() is not None:
        suffix = f" {employee.employee_id}"
        name = f"{base[: 150 - len(suffix)]}{suffix}"

    created = Author(employee_id=employee.employee_id, author_name=name)
    db.add(created)
    await db.flush()
    return created
