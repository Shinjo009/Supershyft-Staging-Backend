"""MetSights Essentials (Basic): vitals optional for Bio AI and completion gates."""

from __future__ import annotations

from collections.abc import Iterable

METSIGHTS_ESSENTIALS_TYPE_CODE = "1"
METSIGHTS_ESSENTIALS_PACKAGE_CODE = "METSIGHTS_BASIC"

OPTIONAL_VITALS_CATEGORY_KEYS = frozenset({"vitals", "health_vitals"})


def is_metsights_essentials(
    *,
    type_code: str | None = None,
    package_code: str | None = None,
) -> bool:
    """True for MetSights Essentials (formerly Basic), assessment type 1."""
    tc = (type_code or "").strip()
    if tc == METSIGHTS_ESSENTIALS_TYPE_CODE:
        return True
    pc = (package_code or "").strip().upper()
    return pc == METSIGHTS_ESSENTIALS_PACKAGE_CODE


def category_optional_for_essentials_completion(category_key: str | None) -> bool:
    """Categories ignored when deciding if an Essentials instance is fully complete."""
    return (category_key or "").strip() in OPTIONAL_VITALS_CATEGORY_KEYS


def is_only_optional_vitals_gap(incomplete_category_keys: Iterable[str]) -> bool:
    """True when every incomplete key is vitals / health_vitals (and at least one)."""
    keys = {(k or "").strip() for k in incomplete_category_keys if (k or "").strip()}
    if not keys:
        return False
    return keys <= OPTIONAL_VITALS_CATEGORY_KEYS


def filter_incomplete_for_essentials_completion(
    incomplete_category_keys: Iterable[str],
    *,
    type_code: str | None,
    package_code: str | None = None,
) -> set[str]:
    """Incomplete keys that still block Essentials completion / Bio AI."""
    keys = {(k or "").strip() for k in incomplete_category_keys if (k or "").strip()}
    if not is_metsights_essentials(type_code=type_code, package_code=package_code):
        return keys
    return {k for k in keys if k not in OPTIONAL_VITALS_CATEGORY_KEYS}
