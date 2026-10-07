"""Shared helpers for paginated admin list endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from common.validation import ValidationError, optional_search_query
from core.exceptions import AppError
from sqlalchemy import asc, desc
from sqlalchemy.sql import ColumnElement

SORT_ASC = "asc"
SORT_DESC = "desc"


@dataclass(frozen=True)
class PageParams:
    page: int
    limit: int


def resolve_page_params(
    *,
    page: int = 1,
    limit: int = 20,
    max_limit: int = 100,
) -> PageParams:
    if page < 1 or limit < 1 or limit > max_limit:
        raise AppError(status_code=400, error_code="INVALID_INPUT", message="Invalid request")
    return PageParams(page=page, limit=limit)


def page_params(
    page: int = 1,
    limit: int = 20,
) -> PageParams:
    return resolve_page_params(page=page, limit=limit)


PageParamsDep = Annotated[PageParams, Depends(page_params)]


def normalize_sort_dir(sort_dir: str | None) -> str:
    if (sort_dir or "").lower() == SORT_ASC:
        return SORT_ASC
    return SORT_DESC


def sanitize_list_search(search: str | None, *, max_len: int = 200) -> str | None:
    """Sanitize optional list/search query string; raises ValidationError on unsafe input."""
    return optional_search_query(search, max_len=max_len)


def ilike_pattern(search: str) -> str:
    escaped = (
        search.strip()
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


def apply_sort(
    query,
    *,
    sort_by: str | None,
    sort_dir: str | None,
    columns: dict[str, ColumnElement],
    default_column: ColumnElement,
):
    direction = asc if normalize_sort_dir(sort_dir) == SORT_ASC else desc
    key = (sort_by or "").strip()
    col = columns.get(key) if key else None
    if col is None:
        return query.order_by(direction(default_column))
    return query.order_by(direction(col), direction(default_column))
