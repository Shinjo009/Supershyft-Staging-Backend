"""Blog queries."""

from __future__ import annotations

import math

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from modules.blog.models import Author, Category, Keyword, Post


class BlogRepository:
    def _post_query(self):
        return select(Post).options(
            selectinload(Post.author).selectinload(Author.partner),
            selectinload(Post.author).selectinload(Author.employee),
            selectinload(Post.category),
            selectinload(Post.keywords),
        )

    async def get_author_by_partner(self, db: AsyncSession, partner_id: int) -> Author | None:
        result = await db.execute(select(Author).where(Author.partner_id == partner_id))
        return result.scalar_one_or_none()

    async def get_post(self, db: AsyncSession, post_id: int) -> Post | None:
        result = await db.execute(self._post_query().where(Post.id == post_id))
        return result.scalar_one_or_none()

    async def slug_taken(self, db: AsyncSession, slug: str, *, exclude_id: int | None = None) -> bool:
        query = select(Post.id).where(Post.slug == slug)
        if exclude_id is not None:
            query = query.where(Post.id != exclude_id)
        result = await db.execute(query.limit(1))
        return result.scalar_one_or_none() is not None

    async def get_category(self, db: AsyncSession, category_id: int) -> Category | None:
        result = await db.execute(select(Category).where(Category.id == category_id))
        return result.scalar_one_or_none()

    async def category_slug_taken(self, db: AsyncSession, slug: str) -> bool:
        result = await db.execute(select(Category.id).where(Category.slug == slug).limit(1))
        return result.scalar_one_or_none() is not None

    async def list_categories(self, db: AsyncSession) -> list[tuple[Category, int]]:
        post_count = func.count(Post.id).label("post_count")
        counts = (
            select(Post.category_id, post_count)
            .group_by(Post.category_id)
            .subquery()
        )
        query = (
            select(Category, func.coalesce(counts.c.post_count, 0))
            .outerjoin(counts, counts.c.category_id == Category.id)
            .order_by(Category.name.asc())
        )
        result = await db.execute(query)
        return [(row[0], int(row[1])) for row in result.all()]

    async def list_posts(
        self,
        db: AsyncSession,
        *,
        status: str,
        category: str,
        search: str,
        page: int,
        limit: int,
    ) -> tuple[list[Post], int, int]:
        page = max(1, page)
        limit = min(50, max(1, limit))
        filters = []
        if status != "all":
            filters.append(Post.status == status)
        if category and category != "all":
            filters.append(Post.category.has(Category.name == category))
        if search:
            like = f"%{search}%"
            filters.append(or_(Post.title.ilike(like), Post.description.ilike(like)))

        count_query = select(func.count(Post.id)).select_from(Post)
        list_query = self._post_query()
        for item in filters:
            count_query = count_query.where(item)
            list_query = list_query.where(item)

        total = int((await db.execute(count_query)).scalar_one())
        rows = await db.execute(
            list_query.order_by(Post.updated_at.desc(), Post.id.desc()).offset((page - 1) * limit).limit(limit)
        )
        posts = list(rows.scalars().unique().all())
        pages = math.ceil(total / limit) if limit else 0
        return posts, total, pages

    async def save_keywords(self, db: AsyncSession, post: Post, focus: str) -> None:
        focus_value = focus.strip() or None
        result = await db.execute(select(Keyword).where(Keyword.post_id == post.id))
        row = result.scalar_one_or_none()
        if row is None:
            db.add(Keyword(post_id=post.id, focus_keyword=focus_value))
            return
        row.focus_keyword = focus_value
