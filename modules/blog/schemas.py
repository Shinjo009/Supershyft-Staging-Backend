"""Request bodies for the blog dashboard."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class PostWrite(BaseModel):
    title: str | None = None
    content: list[dict[str, Any]] | None = Field(
        default=None,
        description="Story blocks stored in the posts.content JSONB column.",
        examples=[[{"tag": "p", "content": "Hello", "marks": []}]],
    )
    category_id: int | None = None
    slug: str | None = None
    description: str | None = None
    thumbnail_url: str | None = None
    background_color: str | None = None
    background_image_url: str | None = None
    status: str | None = None
    focus_keyword: str | list[str] | None = None

    model_config = {
        "extra": "ignore",
        "json_schema_extra": {
            "examples": [
                {
                    "title": "string",
                    "content": [{"tag": "p", "content": "Hello", "marks": []}],
                    "category_id": 0,
                    "slug": "string",
                    "description": "string",
                    "thumbnail_url": "string",
                    "background_color": "#f4faf8",
                    "background_image_url": "string",
                    "status": "string",
                    "focus_keyword": ["AI", "personal growth"],
                }
            ]
        },
    }

    @field_validator("focus_keyword", mode="before")
    @classmethod
    def _coerce_focus_keyword(cls, value):
        if value is None:
            return None
        if isinstance(value, list):
            return [str(part) for part in value]
        return value


class CategoryWrite(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
