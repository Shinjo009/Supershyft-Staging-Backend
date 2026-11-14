"""Staging business API load test — 1000 concurrent user journeys (onboard → auth → questionnaire).

Runs against staging HTTP APIs (no DB required). For DB pool metrics, run on the staging API
host with `.env` loaded and enable ``LOAD_TEST_RATE_LIMIT_RELAXED=true`` on the API.

Examples:

    # Plan only
    python scripts/staging_business_load_test.py --dry-run --max-bots 1000 --concurrency 1000

    # 1000 users at once, each runs onboard + OTP + assessments + questionnaire APIs
    python scripts/staging_business_load_test.py --yes --max-bots 1000 --concurrency 1000 \\
        --mode journey --engagement-code YOURSTAGINGCODE --monitor-health

    # Smoke (legacy single-endpoint mix)
    python scripts/staging_business_load_test.py --yes --max-bots 100 --mode smoke --concurrency 50
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEFAULT_API = os.getenv("STAGING_API", "https://staging-api.supershyft.com")
SINK_PHONE = "8762830757"
SINK_EMAIL = "pratheek.fitnastic@gmail.com"
PHONE_PREFIX = os.getenv("LOAD_TEST_PHONE_PREFIX", "999")  # 10-digit phones: 9990000001 …


@dataclass
class Metrics:
    requests: int = 0
    errors: int = 0
    status_counts: Counter = field(default_factory=Counter)
    latencies_ms: list[float] = field(default_factory=list)
    scenario_counts: Counter = field(default_factory=Counter)
    scenario_errors: Counter = field(default_factory=Counter)

    def record(self, *, status: int, latency_ms: float, scenario: str, ok: bool) -> None:
        self.requests += 1
        self.status_counts[status] += 1
        self.latencies_ms.append(latency_ms)
        self.scenario_counts[scenario] += 1
        if not ok:
            self.errors += 1
            self.scenario_errors[scenario] += 1

    def summary(self) -> dict[str, Any]:
        lat = sorted(self.latencies_ms)
        pct = lambda p: lat[int(len(lat) * p)] if lat else 0.0
        return {
            "requests": self.requests,
            "errors": self.errors,
            "error_rate": round(self.errors / self.requests, 4) if self.requests else 0.0,
            "status_counts": dict(self.status_counts),
            "scenario_counts": dict(self.scenario_counts),
            "scenario_errors": dict(self.scenario_errors),
            "latency_ms": {
                "p50": round(pct(0.50), 2),
                "p95": round(pct(0.95), 2),
                "p99": round(pct(0.99), 2) if len(lat) > 20 else round(pct(0.99), 2),
                "mean": round(statistics.mean(lat), 2) if lat else 0.0,
            },
        }


def _bot_phone(bot_id: int) -> str:
    return f"{PHONE_PREFIX}{bot_id:07d}"[-10:]


def _bot_email(bot_id: int) -> str:
    return f"bot-{bot_id}@example.com"


def _identity(bot_id: int, sink_rate: float, rng: random.Random) -> tuple[str, str, bool]:
    is_sink = rng.random() < sink_rate
    if is_sink:
        return SINK_PHONE, SINK_EMAIL, True
    phone = _bot_phone(bot_id)
    if "dontsendotp" in os.getenv("LOAD_TEST_PHONE_SUFFIX", ""):
        phone = f"{phone}{os.environ['LOAD_TEST_PHONE_SUFFIX']}"
    return phone, _bot_email(bot_id), False


def _auth_headers(access_token: str | None) -> dict[str, str]:
    if not access_token:
        return {}
    return {"Authorization": f"Bearer {access_token}"}


async def _timed_request(
    client: httpx.AsyncClient,
    metrics: Metrics,
    scenario: str,
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    t0 = time.perf_counter()
    try:
        resp = await client.request(method, path, json=json_body, headers=headers, timeout=120.0)
        latency = (time.perf_counter() - t0) * 1000.0
        ok = 200 <= resp.status_code < 300
        metrics.record(status=resp.status_code, latency_ms=latency, scenario=scenario, ok=ok)
        if not ok:
            return {"error": resp.text[:300], "status": resp.status_code}
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text[:300]}
    except Exception as exc:
        latency = (time.perf_counter() - t0) * 1000.0
        metrics.record(status=0, latency_ms=latency, scenario=scenario, ok=False)
        return {"error": str(exc)[:300]}


async def scenario_otp(
    client: httpx.AsyncClient,
    metrics: Metrics,
    *,
    phone: str,
    bypass_otp: str,
) -> None:
    body = {"phone": phone}
    send = await _timed_request(client, metrics, "otp_send", "POST", "/auth/send-otp", json_body=body)
    if not send or "data" not in (send or {}):
        return
    session_id = int((send.get("data") or {}).get("session_id") or 0)
    if not session_id:
        return
    verify_body = {"phone": phone, "otp": bypass_otp}
    return await _timed_request(
        client, metrics, "otp_verify", "POST", "/auth/verify-otp", json_body=verify_body
    )


def _onboard_payload(bot_id: int, phone: str, email: str, *, engagement_code: str | None) -> dict[str, Any]:
    coll = date.today() + timedelta(days=2)
    payload: dict[str, Any] = {
        "age": 28,
        "first_name": "Load",
        "last_name": "Test",
        "email": email,
        "phone": phone,
        "gender": "male",
        "address": "Load Test Address",
        "pincode": "560102",
        "city": "Bengaluru",
        "blood_collection_date": coll.isoformat(),
        "blood_collection_time_slot": "10:00",
    }
    if engagement_code:
        payload["referred_by"] = engagement_code
    return payload


async def scenario_onboard(
    client: httpx.AsyncClient,
    metrics: Metrics,
    *,
    bot_id: int,
    phone: str,
    email: str,
    engagement_code: str | None,
) -> dict[str, Any] | None:
    payload = _onboard_payload(bot_id, phone, email, engagement_code=engagement_code)
    if engagement_code:
        path = f"/users/code/{engagement_code}/onboard"
    else:
        path = "/users/public/onboard"
    return await _timed_request(client, metrics, "onboard", "POST", path, json_body=payload)


async def scenario_login(
    client: httpx.AsyncClient,
    metrics: Metrics,
    *,
    phone: str,
    bypass_otp: str,
) -> str | None:
    send = await _timed_request(client, metrics, "otp_send", "POST", "/auth/send-otp", json_body={"phone": phone})
    if not send or "data" not in send:
        return None
    verify = await _timed_request(
        client,
        metrics,
        "otp_verify",
        "POST",
        "/auth/verify-otp",
        json_body={"phone": phone, "otp": bypass_otp},
    )
    if not verify or "data" not in verify:
        return None
    tokens = (verify.get("data") or {}).get("tokens") or {}
    token = tokens.get("access_token")
    return str(token) if token else None


async def scenario_user_journey(
    client: httpx.AsyncClient,
    metrics: Metrics,
    *,
    bot_id: int,
    phone: str,
    email: str,
    bypass_otp: str,
    engagement_code: str | None,
    rng: random.Random,
) -> None:
    """One virtual user: onboard → login → list assessments → questionnaire draft → profile."""
    onboard = await scenario_onboard(
        client,
        metrics,
        bot_id=bot_id,
        phone=phone,
        email=email,
        engagement_code=engagement_code,
    )
    data = (onboard or {}).get("data") if isinstance(onboard, dict) else None
    assessment_instance_id = int((data or {}).get("assessment_instance_id") or 0)

    token = await scenario_login(client, metrics, phone=phone, bypass_otp=bypass_otp)
    if not token:
        return
    auth = _auth_headers(token)

    await _timed_request(client, metrics, "users_me", "GET", "/users/me", headers=auth)
    assessments = await _timed_request(client, metrics, "assessments_me", "GET", "/assessments/me", headers=auth)
    rows = (assessments or {}).get("data") if isinstance(assessments, dict) else None
    if not assessment_instance_id and isinstance(rows, list) and rows:
        assessment_instance_id = int(rows[0].get("assessment_instance_id") or 0)
    if not assessment_instance_id:
        return

    status = await _timed_request(
        client,
        metrics,
        "assessment_status",
        "GET",
        f"/assessments/{assessment_instance_id}/status",
        headers=auth,
    )
    categories = (status or {}).get("data") if isinstance(status, dict) else None
    if not isinstance(categories, list) or not categories:
        return

    cat = next((c for c in categories if (c.get("status") or "") != "complete"), categories[0])
    category_id = int(cat.get("category_id") or 0)
    if not category_id:
        return

    qnr = await _timed_request(
        client,
        metrics,
        "questionnaire_get",
        "GET",
        f"/questionnaire/{assessment_instance_id}/category/{category_id}?question=unanswered",
        headers=auth,
    )
    questions = (qnr or {}).get("data") if isinstance(qnr, dict) else None
    if isinstance(questions, dict):
        q_list = questions.get("questions") or []
    elif isinstance(questions, list):
        q_list = questions
    else:
        q_list = []

    if q_list:
        take = min(3, len(q_list))
        picked = rng.sample(q_list, k=take) if len(q_list) >= take else q_list
        responses = []
        for q in picked:
            qid = q.get("question_id") if isinstance(q, dict) else None
            if qid is None:
                continue
            responses.append({"question_id": int(qid), "answer": "Load test"})
        if responses:
            await _timed_request(
                client,
                metrics,
                "questionnaire_put",
                "PUT",
                f"/questionnaire/{assessment_instance_id}/category/{category_id}/responses",
                json_body={"responses": responses},
                headers=auth,
            )


async def run_bot(
    client: httpx.AsyncClient,
    metrics: Metrics,
    *,
    bot_id: int,
    sink_rate: float,
    bypass_otp: str,
    weights: dict[str, float],
    rng: random.Random,
    mode: str,
    engagement_code: str | None,
) -> None:
    phone, email, _ = _identity(bot_id, sink_rate, rng)
    if mode == "journey":
        await scenario_user_journey(
            client,
            metrics,
            bot_id=bot_id,
            phone=phone,
            email=email,
            bypass_otp=bypass_otp,
            engagement_code=engagement_code,
            rng=rng,
        )
        return
    roll = rng.random()
    if roll < weights.get("otp", 0.5):
        await scenario_otp(client, metrics, phone=phone, bypass_otp=bypass_otp)
    elif roll < weights.get("otp", 0.5) + weights.get("onboard", 0.35):
        await scenario_onboard(
            client,
            metrics,
            bot_id=bot_id,
            phone=phone,
            email=email,
            engagement_code=engagement_code,
        )
    else:
        await scenario_otp(client, metrics, phone=phone, bypass_otp=bypass_otp)


async def _health_monitor(
    client: httpx.AsyncClient,
    metrics: Metrics,
    *,
    interval_s: float,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        await _timed_request(client, metrics, "health_ping", "GET", "/health")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except asyncio.TimeoutError:
            continue


async def _db_metrics_snapshot() -> dict[str, Any] | None:
    try:
        from sqlalchemy import text

        from db.session import AsyncSessionLocal
    except Exception:
        return None
    out: dict[str, Any] = {}
    try:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT status, COUNT(*)::int AS c
                        FROM notifications
                        WHERE COALESCE(dispatched_at, completed_at) > NOW() - INTERVAL '2 hours'
                        GROUP BY status
                        """
                    )
                )
            ).all()
            out["notifications_last_2h"] = {str(r[0]): int(r[1]) for r in rows}
            pool = (
                await db.execute(
                    text("SELECT COUNT(*)::int FROM pg_stat_activity WHERE datname = current_database()")
                )
            ).scalar_one()
            out["pg_stat_activity_count"] = int(pool)
    except Exception as exc:
        out["error"] = str(exc)[:500]
    return out


async def _seed_users_db(max_bots: int, sink_rate: float) -> dict[str, Any]:
    """Optional DB seed when script runs on staging host with DATABASE_URL."""
    try:
        from sqlalchemy import text

        from db.session import AsyncSessionLocal
    except Exception as exc:
        return {"skipped": str(exc)}

    rng = random.Random(42)
    created = 0
    async with AsyncSessionLocal() as db:
        for bot_id in range(1, max_bots + 1):
            phone, email, _ = _identity(bot_id, sink_rate, rng)
            exists = (
                await db.execute(
                    text("SELECT user_id FROM users WHERE phone = :p LIMIT 1"),
                    {"p": phone},
                )
            ).scalar_one_or_none()
            if exists:
                continue
            await db.execute(
                text(
                    """
                    INSERT INTO users (phone, email, first_name, last_name, created_at, updated_at)
                    VALUES (:phone, :email, :fn, :ln, NOW(), NOW())
                    ON CONFLICT DO NOTHING
                    """
                ),
                {
                    "phone": phone,
                    "email": email,
                    "fn": "Load",
                    "ln": f"Bot{bot_id}",
                },
            )
            created += 1
        await db.commit()
    return {"seeded": created, "max_bots": max_bots}


async def _cleanup_db(max_bots: int) -> dict[str, Any]:
    try:
        from sqlalchemy import text

        from db.session import AsyncSessionLocal
    except Exception as exc:
        return {"skipped": str(exc)}
    pattern = f"{PHONE_PREFIX}%"
    async with AsyncSessionLocal() as db:
        deleted = (
            await db.execute(
                text(
                    """
                    DELETE FROM users
                    WHERE phone LIKE :pattern AND email LIKE 'bot-%@example.com'
                    """
                ),
                {"pattern": pattern},
            )
        ).rowcount
        await db.commit()
    return {"deleted_users": deleted or 0}


async def main_async(args: argparse.Namespace) -> int:
    base = args.api.rstrip("/")
    peak_concurrency = args.concurrency or min(args.max_bots, 1000)
    ramp = [int(x) for x in args.ramp.split(",") if x.strip()]
    if not ramp:
        ramp = [peak_concurrency]
    ramp = sorted({min(args.max_bots, x) for x in ramp})
    weights = {"otp": 0.55, "onboard": 0.35, "other": 0.10}
    engagement_code = (args.engagement_code or os.getenv("LOAD_TEST_ENGAGEMENT_CODE") or "").strip() or None

    plan = {
        "api": base,
        "max_bots": args.max_bots,
        "mode": args.mode,
        "concurrency_peak": min(args.max_bots, max(ramp)),
        "concurrency_ramp": ramp,
        "engagement_code": engagement_code,
        "sink_rate": args.sink_rate,
        "dry_run": args.dry_run,
        "monitor_health": args.monitor_health,
        "weights": weights,
    }
    print(json.dumps({"plan": plan}, indent=2))

    if args.dry_run:
        return 0

    if args.seed_db:
        print(json.dumps({"seed": await _seed_users_db(args.max_bots, args.sink_rate)}, indent=2))

    metrics = Metrics()
    bypass = args.bypass_otp or os.getenv("BYPASS_OTP", "654321")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if args.forwarded_for:
        headers["X-Forwarded-For"] = args.forwarded_for

    peak = min(args.max_bots, max(ramp))
    limits = httpx.Limits(max_connections=peak + 50, max_keepalive_connections=peak)
    stop_health = asyncio.Event()
    t0 = time.perf_counter()
    async with httpx.AsyncClient(base_url=base, headers=headers, limits=limits) as client:
        bot_ids = list(range(1, args.max_bots + 1))
        rng = random.Random(args.seed)
        sweep_limits = ramp if args.ramp_sweeps else [peak]

        health_task: asyncio.Task | None = None
        if args.monitor_health:
            health_task = asyncio.create_task(
                _health_monitor(client, metrics, interval_s=args.health_interval_s, stop=stop_health)
            )

        for concurrency in sweep_limits:
            if concurrency > args.max_bots:
                concurrency = args.max_bots
            sem = asyncio.Semaphore(concurrency)

            async def _one(bid: int, _sem: asyncio.Semaphore = sem) -> None:
                async with _sem:
                    await run_bot(
                        client,
                        metrics,
                        bot_id=bid,
                        sink_rate=args.sink_rate,
                        bypass_otp=bypass,
                        weights=weights,
                        rng=random.Random(rng.randint(0, 2**31 - 1)),
                        mode=args.mode,
                        engagement_code=engagement_code,
                    )

            print(
                json.dumps(
                    {
                        "wave_start": {
                            "concurrency": concurrency,
                            "bots": len(bot_ids),
                            "mode": args.mode,
                            "ramp_sweeps": args.ramp_sweeps,
                        }
                    },
                    indent=2,
                )
            )
            await asyncio.gather(*[_one(bid) for bid in bot_ids])

        stop_health.set()
        if health_task is not None:
            await health_task

    report: dict[str, Any] = {
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "plan": plan,
        "metrics": metrics.summary(),
        "db_snapshot": await _db_metrics_snapshot(),
        "notes": [
            "Set LOAD_TEST_RATE_LIMIT_RELAXED=true on staging API before 1000 concurrent journeys.",
            "Use staging BYPASS_OTP or per-phone bypass for verify-otp.",
            "Watch uvicorn (docker/systemd) and Postgres during the run; health_ping tracks /health while load runs.",
        ],
    }

    if args.cleanup:
        report["cleanup"] = await _cleanup_db(args.max_bots)

    out_path = Path(args.report)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["metrics"]["error_rate"] < 0.05 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Staging business load test")
    parser.add_argument("--yes", action="store_true", help="Execute HTTP load (required with --max-bots)")
    parser.add_argument("--dry-run", action="store_true", help="Print plan only")
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--max-bots", type=int, default=1000)
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Simultaneous virtual users (default: min(max-bots, 1000))",
    )
    parser.add_argument("--ramp", default="1000", help="Concurrency ramp targets (comma-separated)")
    parser.add_argument(
        "--mode",
        choices=("journey", "smoke"),
        default="journey",
        help="journey=onboard+auth+questionnaire per user; smoke=random single endpoints",
    )
    parser.add_argument(
        "--engagement-code",
        default=None,
        help="B2B onboard path (/users/code/{code}/onboard); else B2C public onboard",
    )
    parser.add_argument(
        "--monitor-health",
        action="store_true",
        help="Poll GET /health during the soak to detect uvicorn outages",
    )
    parser.add_argument("--health-interval-s", type=float, default=2.0)
    parser.add_argument(
        "--ramp-sweeps",
        action="store_true",
        help="Run a full bot sweep at each ramp step (heavy; default uses peak concurrency only)",
    )
    parser.add_argument("--sink-rate", type=float, default=0.02, help="Fraction routed to sink phone/email")
    parser.add_argument("--bypass-otp", default=None)
    parser.add_argument("--seed-db", action="store_true", help="Insert missing load-test users (staging host)")
    parser.add_argument("--cleanup", action="store_true", help="Delete bot-*@example.com users after test")
    parser.add_argument("--report", default="scripts/output/load_test_report.json")
    parser.add_argument("--seed", type=int, default=7, help="RNG seed for scenario mix")
    parser.add_argument(
        "--forwarded-for",
        default=None,
        help="Optional X-Forwarded-For (only if staging TRUSTED_PROXIES honors it)",
    )
    args = parser.parse_args()
    if not args.dry_run and not args.yes:
        parser.error("Pass --yes to run HTTP load, or --dry-run to preview")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())