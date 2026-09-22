"""Tests for server health monitoring routes."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import aiosqlite
import pytest

from core.config import settings
from core.security import create_jwt_token
from modules.employee.models import Employee
from modules.server_health.dependencies import get_server_health_service
from modules.server_health.repository import ServerHealthRepository
from modules.server_health.service import ServerHealthService
from modules.users.models import User


def _auth_header(employee_id: int) -> dict[str, str]:
    from tests.helpers.auth import employee_auth_header
    return employee_auth_header(employee_id)


async def _seed_health_db(db_path: Path, *, with_null_overall: bool = False) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE health_runs (
                id INTEGER PRIMARY KEY,
                run_at TEXT,
                ok_count INTEGER,
                warn_count INTEGER,
                crit_count INTEGER,
                overall_status TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE health_checks (
                id INTEGER PRIMARY KEY,
                run_id INTEGER,
                category TEXT,
                status TEXT,
                message TEXT
            )
            """
        )
        await db.executemany(
            """
            INSERT INTO health_runs (id, run_at, ok_count, warn_count, crit_count, overall_status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "2026-07-15 10:00:00", 8, 1, 0, "WARNING"),
                (2, "2026-07-16 10:00:00", 9, 0, 0, "HEALTHY"),
            ],
        )
        if with_null_overall:
            await db.execute(
                """
                INSERT INTO health_runs (id, run_at, ok_count, warn_count, crit_count, overall_status)
                VALUES (3, '2026-07-16 12:00:00', 5, 2, 1, NULL)
                """
            )
        await db.executemany(
            """
            INSERT INTO health_checks (id, run_id, category, status, message)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (1, 2, "MEMORY", "OK", "Memory usage is healthy (20%)"),
                (2, 2, "SYSTEM LOAD", "OK", "Load average is normal"),
                (3, 2, "WEB ENDPOINTS (nginx sites)", "WARN", "tasktracker.supershyft.com unreachable"),
                (4, 1, "MEMORY", "WARN", "Memory usage elevated (85%)"),
            ],
        )
        await db.commit()


@pytest.fixture
async def health_db_path(tmp_path: Path) -> Path:
    db_path = tmp_path / "health.db"
    await _seed_health_db(db_path)
    return db_path


@pytest.fixture
def override_server_health_service(fastapi_app, health_db_path: Path):
    service = ServerHealthService(ServerHealthRepository(str(health_db_path)))
    fastapi_app.dependency_overrides[get_server_health_service] = lambda: service
    yield
    fastapi_app.dependency_overrides.pop(get_server_health_service, None)


@pytest.mark.asyncio
async def test_server_health_current_requires_auth(async_client):
    response = await async_client.get("/server-health/current")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_server_health_current_requires_admin(async_client, test_db_session, override_server_health_service):
    uid = 92001
    test_db_session.add(User(user_id=uid, age=30, phone="92001000001", status="active"))
    await test_db_session.flush()
    test_db_session.add(
        Employee(employee_id=92001, name="Employee 92001", phone="0000092001", email="employee92001@test.example", role="onboarding_assistant", status="active")
    )
    await test_db_session.commit()

    response = await async_client.get("/server-health/current", headers=_auth_header(uid))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_server_health_current_returns_latest_grouped(
    async_client, test_db_session, override_server_health_service
):
    uid = 92002
    test_db_session.add(User(user_id=uid, age=30, phone="92002000001", status="active"))
    await test_db_session.flush()
    test_db_session.add(Employee(employee_id=92002, name="Employee 92002", phone="0000092002", email="employee92002@test.example", role="admin", status="active"))
    await test_db_session.commit()

    response = await async_client.get("/server-health/current", headers=_auth_header(uid))
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["run"]["id"] == 2
    assert body["data"]["run"]["overall_status"] == "HEALTHY"
    categories = {group["category"]: group["checks"] for group in body["data"]["checks_by_category"]}
    assert len(categories["MEMORY"]) == 1
    assert categories["MEMORY"][0]["status"] == "OK"
    assert len(categories["WEB ENDPOINTS (nginx sites)"]) == 1


@pytest.mark.asyncio
async def test_server_health_history_respects_limit_and_dates(
    async_client, test_db_session, override_server_health_service
):
    uid = 92003
    test_db_session.add(User(user_id=uid, age=30, phone="92003000001", status="active"))
    await test_db_session.flush()
    test_db_session.add(Employee(employee_id=92003, name="Employee 92003", phone="0000092003", email="employee92003@test.example", role="admin", status="active"))
    await test_db_session.commit()

    response = await async_client.get(
        "/server-health/history",
        headers=_auth_header(uid),
        params={"limit": 1, "from": "2026-07-16T00:00:00", "to": "2026-07-16T23:59:59"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["id"] == 2
    assert body["meta"]["limit"] == 1
    assert body["meta"]["total"] == 1


@pytest.mark.asyncio
async def test_server_health_returns_503_when_db_missing(async_client, test_db_session, fastapi_app, tmp_path):
    missing_path = tmp_path / "missing.db"
    service = ServerHealthService(ServerHealthRepository(str(missing_path)))
    fastapi_app.dependency_overrides[get_server_health_service] = lambda: service

    uid = 92004
    test_db_session.add(User(user_id=uid, age=30, phone="92004000001", status="active"))
    await test_db_session.flush()
    test_db_session.add(Employee(employee_id=92004, name="Employee 92004", phone="0000092004", email="employee92004@test.example", role="admin", status="active"))
    await test_db_session.commit()

    response = await async_client.get("/server-health/current", headers=_auth_header(uid))
    assert response.status_code == 503
    assert "not available" in response.json()["message"].lower()

    fastapi_app.dependency_overrides.pop(get_server_health_service, None)


@pytest.mark.asyncio
async def test_server_health_tolerates_null_overall_status(async_client, test_db_session, fastapi_app, tmp_path):
    """Production health.db may store NULL overall_status; API must coerce, not 500."""
    db_path = tmp_path / "health_null.db"
    await _seed_health_db(db_path, with_null_overall=True)
    service = ServerHealthService(ServerHealthRepository(str(db_path)))
    fastapi_app.dependency_overrides[get_server_health_service] = lambda: service

    uid = 92005
    test_db_session.add(User(user_id=uid, age=30, phone="92005000001", status="active"))
    await test_db_session.flush()
    test_db_session.add(Employee(employee_id=92005, name="Employee 92005", phone="0000092005", email="employee92005@test.example", role="admin", status="active"))
    await test_db_session.commit()

    current = await async_client.get("/server-health/current", headers=_auth_header(uid))
    assert current.status_code == 200
    assert current.json()["data"]["run"]["id"] == 3
    assert current.json()["data"]["run"]["overall_status"] == "CRITICAL"

    history = await async_client.get(
        "/server-health/history",
        headers=_auth_header(uid),
        params={"limit": 50},
    )
    assert history.status_code == 200
    statuses = {row["id"]: row["overall_status"] for row in history.json()["data"]}
    assert statuses[3] == "CRITICAL"

    fastapi_app.dependency_overrides.pop(get_server_health_service, None)


HEALTH_METRICS_TOKEN = "test-health-api-token"


def _metrics_payload(**overrides) -> dict:
    payload = {
        "hostname": "prod-1",
        "cpu_usage": 40,
        "memory_usage": 55,
        "storage_usage": 62,
        "load_1m": 1.25,
        "cores": 4,
        "timestamp": "2026-09-22T06:00:00Z",
    }
    payload.update(overrides)
    return payload


def _health_api_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {HEALTH_METRICS_TOKEN}"}


@pytest.fixture
def health_api_token(monkeypatch):
    monkeypatch.setattr(settings, "HEALTH_API_TOKEN", HEALTH_METRICS_TOKEN)
    monkeypatch.setattr(settings, "CPU_ALERT_THRESHOLD_PCT", 75.0)
    monkeypatch.setattr(settings, "CPU_ALERT_SERVICE_KEY", "cpu_above_threshold")
    monkeypatch.setattr(settings, "CPU_ALERT_USER_IDS", "5,6,7")
    return HEALTH_METRICS_TOKEN


@pytest.fixture
def capturing_cpu_dispatch(monkeypatch):
    calls: list[dict] = []

    async def _dispatch(self, db, *, payload, triggered_by_user_id=None):
        calls.append(
            {
                "service_key": payload.service_key,
                "user_ids": list(payload.user_ids),
                "participant_details": payload.participant_details,
            }
        )
        return {"notification_id": 901, "status": "pending", "message": "Webhook called successfully"}

    monkeypatch.setattr(
        "modules.notifications.service.NotificationsService.dispatch",
        _dispatch,
    )
    return calls


@pytest.mark.asyncio
async def test_server_health_metrics_requires_token(async_client, health_api_token):
    response = await async_client.post("/server-health/metrics", json=_metrics_payload())
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_server_health_metrics_rejects_wrong_token(async_client, health_api_token):
    response = await async_client.post(
        "/server-health/metrics",
        json=_metrics_payload(),
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_server_health_metrics_below_threshold_does_not_dispatch(
    async_client, health_api_token, capturing_cpu_dispatch
):
    response = await async_client.post(
        "/server-health/metrics",
        json=_metrics_payload(cpu_usage=40),
        headers=_health_api_headers(),
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["accepted"] is True
    assert body["above_threshold"] is False
    assert body["alert_action"] == "none"
    assert capturing_cpu_dispatch == []


@pytest.mark.asyncio
async def test_server_health_metrics_dispatches_once_while_above_threshold(
    async_client, health_api_token, capturing_cpu_dispatch
):
    first = await async_client.post(
        "/server-health/metrics",
        json=_metrics_payload(cpu_usage=82),
        headers=_health_api_headers(),
    )
    assert first.status_code == 200
    assert first.json()["data"]["alert_action"] == "alerted"
    assert capturing_cpu_dispatch[0]["service_key"] == "cpu_above_threshold"
    assert capturing_cpu_dispatch[0]["user_ids"] == [5, 6, 7]

    second = await async_client.post(
        "/server-health/metrics",
        json=_metrics_payload(cpu_usage=91),
        headers=_health_api_headers(),
    )
    assert second.status_code == 200
    assert second.json()["data"]["alert_action"] == "already_alerting"
    assert len(capturing_cpu_dispatch) == 1


@pytest.mark.asyncio
async def test_server_health_metrics_recovers_then_alerts_again(
    async_client, health_api_token, capturing_cpu_dispatch
):
    await async_client.post(
        "/server-health/metrics",
        json=_metrics_payload(cpu_usage=88),
        headers=_health_api_headers(),
    )
    recovered = await async_client.post(
        "/server-health/metrics",
        json=_metrics_payload(cpu_usage=20),
        headers=_health_api_headers(),
    )
    assert recovered.json()["data"]["alert_action"] == "recovered"
    assert recovered.json()["data"]["is_alerting"] is False
    assert len(capturing_cpu_dispatch) == 1

    again = await async_client.post(
        "/server-health/metrics",
        json=_metrics_payload(cpu_usage=80),
        headers=_health_api_headers(),
    )
    assert again.json()["data"]["alert_action"] == "alerted"
    assert len(capturing_cpu_dispatch) == 2


@pytest.mark.asyncio
async def test_server_health_metrics_dispatch_failure_does_not_latch(
    async_client, health_api_token, monkeypatch
):
    async def _fail(self, db, **kwargs):
        raise RuntimeError("n8n down")

    monkeypatch.setattr(
        "modules.notifications.service.NotificationsService.dispatch",
        _fail,
    )
    first = await async_client.post(
        "/server-health/metrics",
        json=_metrics_payload(cpu_usage=90),
        headers=_health_api_headers(),
    )
    assert first.status_code == 200
    assert first.json()["data"]["alert_action"] == "alert_failed"
    assert first.json()["data"]["is_alerting"] is False


@pytest.mark.asyncio
async def test_server_health_current_overlays_posted_metrics(
    async_client, test_db_session, override_server_health_service, health_api_token, capturing_cpu_dispatch
):
    uid = 92006
    test_db_session.add(User(user_id=uid, age=30, phone="92006000001", status="active"))
    await test_db_session.flush()
    test_db_session.add(
        Employee(
            employee_id=92006,
            name="Employee 92006",
            phone="0000092006",
            email="employee92006@test.example",
            role="admin",
            status="active",
        )
    )
    await test_db_session.commit()

    posted = await async_client.post(
        "/server-health/metrics",
        json=_metrics_payload(cpu_usage=41, memory_usage=33, storage_usage=70, load_1m=0.8, cores=8),
        headers=_health_api_headers(),
    )
    assert posted.status_code == 200

    response = await async_client.get("/server-health/current", headers=_auth_header(uid))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["run"]["cpu_pct"] == 41
    assert data["run"]["mem_pct"] == 33
    assert data["run"]["storage_pct"] == 70
    assert data["latest_metrics"]["hostname"] == "prod-1"
    assert data["latest_metrics"]["load_1m"] == 0.8
    assert data["latest_metrics"]["cores"] == 8
    assert data["cpu_alert"]["is_alerting"] is False
    assert data["cpu_alert"]["threshold_pct"] == 75.0
