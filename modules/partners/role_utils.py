"""Normalize partner role values from ORM enums and API inputs."""

from __future__ import annotations

import enum


def partner_role_value(role: object | None) -> str:
    """Return the canonical partner role string.

    ORM columns use ``PartnerRoleEnum`` (db.column_types) while API/code often
    uses ``PartnerRole`` (modules.partners.models). Those are distinct enum
    classes with the same values. ``str(orm_role)`` yields
    ``"PartnerRoleEnum.organization_manager"``, which breaks comparisons —
    always prefer ``.value`` for enums.
    """
    if role is None:
        return ""
    if isinstance(role, enum.Enum):
        return str(role.value)
    return str(role)
