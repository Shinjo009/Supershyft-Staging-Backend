"""LOAD_TEST_RATE_LIMIT_RELAXED toggles auth OTP limits."""

from core.config import settings
from core.rate_limit import auth_otp_rate_limit, user_onboard_rate_limit, verify_otp_rate_limit


def test_auth_otp_rate_limit_relaxed(monkeypatch):
    monkeypatch.setattr(settings, "LOAD_TEST_RATE_LIMIT_RELAXED", True, raising=False)
    assert auth_otp_rate_limit() == "10000/minute"


def test_auth_otp_rate_limit_default(monkeypatch):
    monkeypatch.setattr(settings, "LOAD_TEST_RATE_LIMIT_RELAXED", False, raising=False)
    assert auth_otp_rate_limit() == "5/minute"


def test_onboard_and_verify_limits_relaxed(monkeypatch):
    monkeypatch.setattr(settings, "LOAD_TEST_RATE_LIMIT_RELAXED", True, raising=False)
    assert user_onboard_rate_limit() == "10000/minute"
    assert verify_otp_rate_limit() == "10000/minute"