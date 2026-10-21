"""Blog dashboard and public read APIs."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.exceptions import AppError
from modules.blog.content import (
    blocks_are_empty,
    normalize_blocks,
    parse_keyword_value,
    present_blocks,
    read_minutes,
    story_chars,
)
from modules.blog.errors import ApiError
from modules.blog.models import Author, Category, Post
from modules.blog.repository import BlogRepository
from modules.blog.schemas import CategoryWrite, PostWrite
from modules.blog.textutil import as_int, fmt_dt, make_slug

MAX_TITLE_CHARS = 200
MAX_DESCRIPTION_CHARS = 500
MAX_STORY_CHARS = 100_000
IMAGE_MAX_BYTES = 5 * 1024 * 1024
_HEX_COLOR = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_MEDIA_TYPES = {
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/wav": ".wav",
    "audio/ogg": ".ogg",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}
_ALLOWED = {**_IMAGE_TYPES, **_MEDIA_TYPES}


def _enum_text(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _sniff_media(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"ID3"):
        return "audio/mpeg"
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0 and (data[1] & 0x06) != 0:
        return "audio/mpeg"
    if data.startswith(b"OggS"):
        return "audio/ogg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        size = int.from_bytes(data[:4], "big")
        end = min(len(data), size if 16 <= size <= 256 else 64)
        brands = data[8:end]
        if b"M4A " in brands or b"M4B " in brands:
            return "audio/mp4"
        return "video/mp4"
    return None


class BlogService:
    def __init__(self, repository: BlogRepository | None = None):
        self._repository = repository or BlogRepository()

    async def list_posts(
        self,
        db: AsyncSession,
        *,
        status: str,
        category: str,
        search: str,
        page: int,
        limit: int,
        public_only: bool = False,
    ) -> dict:
        status_filter = (status or "all").strip() or "all"
        if public_only:
            status_filter = "published"
        posts, total, pages = await self._repository.list_posts(
            db,
            status=status_filter,
            category=category,
            search=search,
            page=page,
            limit=limit,
        )
        return {
            "posts": [self._list_item(post) for post in posts],
            "total": total,
            "page": max(1, page),
            "limit": min(50, max(1, limit)),
            "totalPages": pages,
        }

    async def get_post(self, db: AsyncSession, post_id: int, *, public_only: bool = False) -> dict:
        post = await self._repository.get_post(db, post_id)
        if post is None:
            raise ApiError("Post not found", 404)
        if public_only and _enum_text(post.status) != "published":
            raise ApiError("Post not found", 404)
        return {"post": self._detail(post)}

    async def create_post(self, db: AsyncSession, body: PostWrite, author: Author) -> dict:
        title = self._title(body.title, required=True)
        content = self._story(body)
        category_id = await self._category_id(db, body.category_id)
        slug_source = (body.slug or "").strip() or make_slug(title) or "post"
        slug = await self._unique_slug(db, slug_source)
        status = self._status(body.status)
        published_at = datetime.now(timezone.utc) if status == "published" else None
        post = Post(
            title=title,
            slug=slug,
            content=content,
            description=self._description(body.description),
            thumbnail_url=(body.thumbnail_url or "").strip() or None,
            background_color=self._background_color(body.background_color),
            background_image_url=self._background_image(body.background_image_url),
            category_id=category_id,
            author_id=author.id,
            status=status,
            published_at=published_at,
        )
        db.add(post)
        await db.flush()
        await self._repository.save_keywords(db, post, self._focus_keyword_store(body.focus_keyword))
        await db.flush()
        return {"success": True, "id": post.id, "slug": post.slug}

    async def update_post(self, db: AsyncSession, post_id: int, body: PostWrite, author: Author) -> dict:
        post = await self._repository.get_post(db, post_id)
        if post is None:
            raise ApiError("Post not found", 404)
        self._assert_can_mutate(post, author)
        status = self._status(body.status)
        post.title = self._title(body.title, required=True)
        post.content = self._story(body)
        post.description = self._description(body.description)
        post.thumbnail_url = (body.thumbnail_url or "").strip() or None
        post.background_color = self._background_color(body.background_color)
        post.background_image_url = self._background_image(body.background_image_url)
        post.category_id = await self._category_id(db, body.category_id)
        post.status = status
        if body.slug and body.slug.strip() and body.slug.strip() != post.slug:
            post.slug = await self._unique_slug(db, body.slug.strip(), exclude_id=post.id)
        if status == "published" and post.published_at is None:
            post.published_at = datetime.now(timezone.utc)
        await self._repository.save_keywords(db, post, self._focus_keyword_store(body.focus_keyword))
        await db.flush()
        return {"success": True, "id": post.id, "slug": post.slug}

    async def delete_post(self, db: AsyncSession, post_id: int, author: Author) -> dict:
        post = await self._repository.get_post(db, post_id)
        if post is None:
            raise ApiError("Post not found", 404)
        self._assert_can_mutate(post, author)
        await db.delete(post)
        await db.flush()
        return {"success": True}

    async def list_categories(self, db: AsyncSession) -> dict:
        rows = await self._repository.list_categories(db)
        return {
            "categories": [
                {"id": row.id, "name": row.name, "slug": row.slug, "post_count": count}
                for row, count in rows
            ]
        }

    async def create_category(self, db: AsyncSession, body: CategoryWrite) -> dict:
        name = body.name.strip()
        if not name:
            raise ApiError("Category name is required")
        row = Category(name=name, slug=await self._unique_category_slug(db, name))
        db.add(row)
        await db.flush()
        return {"success": True, "category": {"id": row.id, "name": row.name, "slug": row.slug}}

    async def update_category(self, db: AsyncSession, category_id: int, body: CategoryWrite) -> dict:
        row = await self._repository.get_category(db, category_id)
        if row is None:
            raise ApiError("Category not found", 404)
        name = body.name.strip()
        if not name:
            raise ApiError("Category name is required")
        row.name = name
        await db.flush()
        return {"success": True, "category": {"id": row.id, "name": row.name, "slug": row.slug}}

    async def delete_category(self, db: AsyncSession, category_id: int) -> dict:
        row = await self._repository.get_category(db, category_id)
        if row is None:
            raise ApiError("Category not found", 404)
        await db.delete(row)
        await db.flush()
        return {"success": True}

    async def save_upload(self, upload: UploadFile) -> str:
        if upload is None or not upload.filename:
            raise ApiError("No file uploaded")
        data = await upload.read()
        if not data:
            raise ApiError("No file uploaded")
        mime = _sniff_media(data)
        if mime not in _ALLOWED:
            raise ApiError(
                "Invalid file type. Only JPG, PNG, WebP, GIF, MP3, M4A, WAV, OGG, MP4, and WebM are allowed."
            )
        limit = IMAGE_MAX_BYTES if mime in _IMAGE_TYPES else settings.MAX_REQUEST_BODY_MB * 1024 * 1024
        if len(data) > limit:
            megabytes = max(1, limit // (1024 * 1024))
            raise ApiError(f"File too large. Max {megabytes} MB.")
        folder = Path(settings.MEDIA_ROOT) / "blog"
        folder.mkdir(parents=True, exist_ok=True)
        filename = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4) + _ALLOWED[mime]
        dest = (folder / filename).resolve()
        if folder.resolve() not in dest.parents:
            raise ApiError("Invalid file name")
        dest.write_bytes(data)
        return f"{settings.MEDIA_BASE_URL.rstrip('/')}/blog/{filename}"

    async def _unique_slug(self, db: AsyncSession, slug: str, *, exclude_id: int | None = None) -> str:
        base = make_slug(slug) or "post"
        candidate = base
        index = 1
        while await self._repository.slug_taken(db, candidate, exclude_id=exclude_id):
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    async def _unique_category_slug(self, db: AsyncSession, name: str) -> str:
        base = make_slug(name) or "category"
        candidate = base
        index = 1
        while await self._repository.category_slug_taken(db, candidate):
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    async def _category_id(self, db: AsyncSession, value) -> int:
        category_id = as_int(value, 0)
        if category_id <= 0 or await self._repository.get_category(db, category_id) is None:
            raise ApiError("Field 'category_id' is required")
        return category_id

    def _story(self, body: PostWrite) -> list:
        blocks = normalize_blocks(body.content, site_url=settings.MEDIA_BASE_URL)
        if blocks_are_empty(blocks):
            raise ApiError("Field 'content' is required")
        if story_chars(blocks) > MAX_STORY_CHARS:
            raise ApiError("Blog content must be at most 100,000 characters")
        return blocks

    def _title(self, value: str | None, *, required: bool) -> str:
        title = (value or "").strip()
        if required and not title:
            raise ApiError("Field 'title' is required")
        if len(title) > MAX_TITLE_CHARS:
            raise ApiError("Field 'title' must be at most 200 characters")
        return title

    def _description(self, value: str | None) -> str:
        text = (value or "").strip()
        if len(text) > MAX_DESCRIPTION_CHARS:
            raise ApiError("Field 'description' must be at most 500 characters")
        return text

    def _status(self, value: str | None) -> str:
        if value is None or not str(value).strip():
            return "draft"
        status = str(value).strip()
        if status not in {"draft", "published"}:
            raise ApiError("Field 'status' must be draft or published")
        return status

    def _background_color(self, value: str | None) -> str | None:
        text = (value or "").strip()
        if not text:
            return None
        if not _HEX_COLOR.match(text):
            raise ApiError("Background color must be a hex color like #rgb or #rrggbb")
        if len(text) == 4:
            _, r, g, b = text
            text = f"#{r}{r}{g}{g}{b}{b}"
        return text.lower()

    def _background_image(self, value: str | None) -> str | None:
        """Validate a page wallpaper URL."""
        raw = (value or "").strip()
        if not raw:
            return None
        blocks = normalize_blocks(
            [{"tag": "img", "attributes": {"src": raw, "alt": ""}}],
            site_url=settings.MEDIA_BASE_URL,
        )
        attrs = blocks[0].get("attributes") if blocks else None
        src = attrs.get("src") if isinstance(attrs, dict) else None
        if not blocks or blocks[0].get("tag") != "img" or not src:
            raise ApiError("Invalid background image")
        return str(src)

    def _list_item(self, post: Post) -> dict:
        author = post.author
        return {
            "id": post.id,
            "title": post.title,
            "slug": post.slug,
            "description": post.description,
            "thumbnail_url": post.thumbnail_url,
            "background_color": post.background_color,
            "background_image_url": post.background_image_url,
            "author_name": author.author_name if author else "",
            "author_role": _enum_text(author.author_role) if author else "",
            "avatar_url": author.avatar_url if author else None,
            "published_at": fmt_dt(post.published_at),
            "read_time": read_minutes(post.content or []),
            "status": _enum_text(post.status),
            "category": post.category.name if post.category else None,
        }

    def _detail(self, post: Post) -> dict:
        author = post.author
        tags = self._focus_keyword_tags(
            post.keywords.focus_keyword if post.keywords else None
        )
        return {
            "id": post.id,
            "title": post.title,
            "slug": post.slug,
            "content": present_blocks(post.content),
            "description": post.description,
            "thumbnail_url": post.thumbnail_url,
            "background_color": post.background_color,
            "background_image_url": post.background_image_url,
            "category_id": post.category_id,
            "author_name": author.author_name if author else "",
            "author_role": _enum_text(author.author_role) if author else "",
            "author_bio": author.author_bio if author and author.author_bio else "",
            "avatar_url": author.avatar_url if author else None,
            "status": _enum_text(post.status),
            "focus_keyword": ", ".join(tags),
            "read_time": read_minutes(post.content or []),
            "published_at": fmt_dt(post.published_at),
            "created_at": fmt_dt(post.created_at),
            "updated_at": fmt_dt(post.updated_at),
            "category": post.category.name if post.category else None,
        }

    def _assert_can_mutate(self, post: Post, author: Author) -> None:
        """Partner authors may change only their own posts; admin employees may change any."""
        if author.employee_id is not None:
            return
        if post.author_id == author.id:
            return
        raise AppError(
            status_code=403,
            error_code="FORBIDDEN",
            message="You do not have permission to perform this action",
        )

    def _focus_keyword_store(self, value: str | list[str] | None) -> str:
        tags = self._focus_keyword_tags(value)
        return ", ".join(tags)

    def _focus_keyword_tags(self, value) -> list[str]:
        items = parse_keyword_value(value) or []
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            text = str(item).strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
        return out
