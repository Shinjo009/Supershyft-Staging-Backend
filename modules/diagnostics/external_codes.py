"""Helpers for diagnostic provider external package/parameter codes."""

from __future__ import annotations


def healthians_package_deal_id(external_package_code: str | None) -> str:
    """Build Healthians deal id string from stored external package code."""
    raw = (external_package_code or "").strip()
    if not raw:
        return "package_0"
    return f"package_{int(raw)}"


def healthians_product_deal_type_id(external_package_code: str | None) -> int:
    raw = (external_package_code or "").strip()
    if not raw:
        return 0
    return int(raw)
