"""Helpers for user API serialization."""

from __future__ import annotations

from datetime import date

from modules.users.age_policy import user_computed_age
from modules.users.models import User


def api_age_for_user(user: User, *, business_date: date | None = None) -> int | None:
    return user_computed_age(user, business_date=business_date)


def api_age_for_user_response(user: User, *, business_date: date | None = None) -> int:
    computed = user_computed_age(user, business_date=business_date)
    if computed is not None:
        return computed
    return int(user.age or 0)