"""Rate-limiting configuration backed by slowapi."""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from core.network import get_client_ip

limiter = Limiter(key_func=get_client_ip, default_limits=[])


def _load_test_limit(default: str) -> str:
    from core.config import settings

    if settings.LOAD_TEST_RATE_LIMIT_RELAXED:
        return "10000/minute"
    return default


def auth_otp_rate_limit() -> str:
    """Staging load tests may raise send-otp limits via LOAD_TEST_RATE_LIMIT_RELAXED."""
    return _load_test_limit("5/minute")


def user_onboard_rate_limit() -> str:
    return _load_test_limit("3/minute")


def verify_otp_rate_limit() -> str:
    return _load_test_limit("10/minute")
