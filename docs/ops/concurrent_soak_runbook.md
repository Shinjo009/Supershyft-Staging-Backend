# 1000 concurrent users — staging soak runbook

## Goal

Simulate **1000 users at the same time**, each doing real work: **onboard → OTP login → profile → assessments → questionnaire saves**. Use this to see whether **uvicorn** and **Postgres** stay up (not just whether one endpoint returns 200).

## Staging API process model

Staging runs **4 uvicorn workers** (`staging-api.service` / `deploy_staging_backend.sh`). Each worker has its own DB pool; keep `4 * (DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW)` under Postgres `max_connections`.

## 1. Staging API prep (required)

On the staging API host, in `.env` for the test window:

```bash
LOAD_TEST_RATE_LIMIT_RELAXED=true
ALLOW_BYPASS_OTP=true          # or BYPASS_OTP_BY_PHONE for load phones
BYPASS_OTP=654321             # must match --bypass-otp below
```

Deploy the backend branch that includes rate-limit relax + load script, then restart uvicorn.

Optional: set a dedicated B2B engagement code (recommended for corporate-style onboard):

```bash
export LOAD_TEST_ENGAGEMENT_CODE=your-staging-engagement-code
```

## 2. Run the soak

**Best:** run on the staging server (lower latency, can attach DB metrics):

```bash
cd /var/www/staging-api && source venv/bin/activate
python scripts/staging_business_load_test.py --yes \
  --max-bots 1000 --concurrency 1000 --mode journey \
  --engagement-code "$LOAD_TEST_ENGAGEMENT_CODE" \
  --monitor-health --sink-rate 0 \
  --bypass-otp 654321 \
  --report docs/ops/load_test_report.json
```

From your laptop (works, but watch single-IP limits if `LOAD_TEST_RATE_LIMIT_RELAXED` is off):

```bash
python scripts/staging_business_load_test.py --yes --max-bots 1000 --concurrency 1000 --mode journey --monitor-health
```

## 3. What to watch on the server

| Signal | Command / place |
|--------|------------------|
| Uvicorn alive | `health_ping` in report; `curl -s $API/health` |
| DB connections | `pg_stat_activity`; report `pg_stat_activity_count` when script runs on host |
| Pool exhaustion | API logs: pool timeout; consider raising `DATABASE_POOL_SIZE` temporarily on staging |
| Process crash | systemd/docker restart count, OOM in `dmesg` |

## 4. Per-user journey (what hits the DB)

1. `POST /users/public/onboard` or `POST /users/code/{code}/onboard`
2. `POST /auth/send-otp` + `POST /auth/verify-otp`
3. `GET /users/me`
4. `GET /assessments/me`
5. `GET /assessments/{id}/status`
6. `GET /questionnaire/{id}/category/{cat}`
7. `PUT /questionnaire/.../responses` (draft answers)

Success threshold in the script: overall HTTP error rate &lt; 5% (adjust after staging is configured).

## 5. Cleanup

```bash
python scripts/staging_business_load_test.py --yes --max-bots 1000 --dry-run  # no-op
# optional on staging host:
python scripts/staging_business_load_test.py --yes --max-bots 1 --cleanup
```

Turn off `LOAD_TEST_RATE_LIMIT_RELAXED` after the test.