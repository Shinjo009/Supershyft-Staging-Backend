import pytest
from fastapi import BackgroundTasks
from starlette.requests import Request

from modules.notifications.delivery_scheduler import (
    SYNC_DELIVERY_PATHS,
    BackgroundDeliveryScheduler,
    DeliveryScheduler,
    bind_notification_delivery_scheduler,
    get_delivery_scheduler,
    path_requires_sync_delivery,
)


@pytest.mark.asyncio
async def test_sync_scheduler_runs_inline():
    scheduler = DeliveryScheduler()
    assert scheduler.defer_enabled is False
    ran = False

    async def work(db):
        nonlocal ran
        ran = True

    fake_db = object()
    await scheduler.invoke(work, db=fake_db)  # type: ignore[arg-type]
    assert ran


@pytest.mark.asyncio
async def test_background_scheduler_defers_when_enabled(monkeypatch):
    monkeypatch.setattr(
        "modules.notifications.delivery_scheduler.settings.NOTIFICATION_DEFER_HTTP_DELIVERY",
        True,
    )
    bg = BackgroundTasks()
    scheduler = BackgroundDeliveryScheduler(bg)
    assert scheduler.defer_enabled is True
    ran = False

    async def work(db):
        nonlocal ran
        ran = True

    await scheduler.invoke(work, db=object())  # type: ignore[arg-type]
    assert not ran
    await bg()  # run enqueued tasks in tests
    assert ran


@pytest.mark.asyncio
async def test_background_scheduler_inline_when_flag_disabled(monkeypatch):
    monkeypatch.setattr(
        "modules.notifications.delivery_scheduler.settings.NOTIFICATION_DEFER_HTTP_DELIVERY",
        False,
    )
    scheduler = BackgroundDeliveryScheduler(BackgroundTasks())
    ran = False

    async def work(db):
        nonlocal ran
        ran = True

    await scheduler.invoke(work, db=object())  # type: ignore[arg-type]
    assert ran


def test_sync_delivery_path_allowlist():
    scope = {"type": "http", "method": "POST", "path": "/notifications/callback", "headers": []}
    request = Request(scope)
    assert path_requires_sync_delivery(request) is True
    scope["path"] = "/auth/send-otp"
    assert path_requires_sync_delivery(Request(scope)) is False
    assert "/notifications/callback" in SYNC_DELIVERY_PATHS


@pytest.mark.asyncio
async def test_bind_dependency_sets_sync_scheduler_on_allowlisted_path():
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/notifications/callback",
        "headers": [],
    }
    request = Request(scope)
    bg = BackgroundTasks()
    gen = bind_notification_delivery_scheduler(request, bg)
    await gen.__anext__()
    try:
        assert get_delivery_scheduler().defer_enabled is False
    finally:
        await gen.aclose()