"""Slug and reading-time helpers for blog posts."""

from __future__ import annotations

import math
import re
from datetime import datetime

_TAG_RE = re.compile(r"<[^>]+>")
_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_SLUG_BAD = re.compile(r"[^a-z0-9\s-]")
_SLUG_DASH = re.compile(r"[\s-]+")


def make_slug(title: str) -> str:
    slug = title.lower().strip()
    slug = _SLUG_BAD.sub("", slug)
    slug = _SLUG_DASH.sub("-", slug)
    return slug.strip("-")


def calc_read_time(content: str) -> int:
    text = _TAG_RE.sub(" ", content or "")
    words = _WORD_RE.findall(text)
    return max(1, math.ceil(len(words) / 200))


def fmt_dt(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    text = str(value).strip()
    if not text:
        return None
    return text.replace("T", " ")[:19]


def as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
