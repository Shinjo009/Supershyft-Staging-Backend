"""Short-lived in-process cache for slim dashboard overview KPIs."""

from __future__ import annotations

import time
from typing import Any

_OVERVIEW_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_OVERVIEW_TTL_SECONDS = 60.0


def overview_cache_key(*, employee_id: int) -> str:
    return f"employee:{employee_id}"


def get_cached_overview(key: str) -> dict[str, Any] | None:
    entry = _OVERVIEW_CACHE.get(key)
    if entry is None:
        return None
    expires_at, payload = entry
    if time.monotonic() >= expires_at:
        _OVERVIEW_CACHE.pop(key, None)
        return None
    return payload


def set_cached_overview(key: str, payload: dict[str, Any]) -> None:
    _OVERVIEW_CACHE[key] = (time.monotonic() + _OVERVIEW_TTL_SECONDS, payload)


def clear_overview_cache() -> None:
    _OVERVIEW_CACHE.clear()
