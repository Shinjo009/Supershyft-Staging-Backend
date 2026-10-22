"""Tests for notification event engine."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from modules.notifications.engine import emit_notification_event


@pytest.mark.asyncio
async def test_emit_unknown_event_skips_in_test_raises():
    with (
        patch("modules.notifications.engine.settings.APP_ENVIRONMENT", "test"),
        pytest.raises(ValueError, match="Unknown notification event_code"),
    ):
        await emit_notification_event(
            None,
            "not_a_real_event_code_xyz",
            {},
        )


@pytest.mark.asyncio
async def test_emit_calls_dispatch_when_bindings_exist():
    mock_service = AsyncMock()
    mock_service.dispatch = AsyncMock(return_value={"notification_id": 42, "status": "queued", "message": "ok"})
    mock_service._repo = AsyncMock()

    from modules.notifications.engine import _Binding

    bindings = [
        _Binding(
            recipient_type="participant",
            notification_services=[{"service_key": "test-svc"}],
            event_name="Test",
        )
    ]

    with (
        patch("modules.notifications.engine._load_bindings", AsyncMock(return_value=bindings)),
        patch(
            "modules.notifications.engine.resolve_recipients",
            AsyncMock(return_value=[{"user_id": 1, "first_name": "A", "phone": "1", "email": ""}]),
        ),
        patch("modules.notifications.engine.should_skip_notification", AsyncMock(return_value=None)),
    ):
        ids = await emit_notification_event(
            None,
            "otp_whatsapp",
            {"user_id": 1, "otp": "123456"},
            notifications_service=mock_service,
            skip_dedup=True,
        )

    assert ids == [42]
    mock_service.dispatch.assert_awaited_once()
