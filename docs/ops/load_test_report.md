# Staging 1000-bot load test report

**Date:** 2026-11-14  
**Target:** `https://staging-api.supershyft.com`  
**Harness:** `scripts/staging_business_load_test.py`  
**Raw JSON:** [`load_test_report.json`](load_test_report.json)

## Configuration

| Parameter | Value |
|-----------|--------|
| `max_bots` | 1000 |
| Peak concurrency | 20 (single sweep) |
| `sink_rate` | 1% → `8762830757` / `pratheek.fitnastic@gmail.com` |
| Scenario mix | 55% OTP send, 35% public onboard, 10% (reserved) |
| Code changes on staging | **Not deployed yet** (`LOAD_TEST_RATE_LIMIT_RELAXED`, email skip, defer failure handling) |

## Results (concurrency 20)

| Metric | Value |
|--------|--------|
| HTTP requests | 1000 |
| Error rate | **100%** (expected without rate-limit bypass) |
| Status breakdown | **429** (633), **400** (362), **404** (5) |
| Latency p50 / p95 | ~151 ms / ~518 ms |
| OTP curl smoke (8762830757) | **200**, `channels: ["phone"]` only |

### Interpretation

1. **`/auth/send-otp` is limited to 5/minute per client IP** on current staging. A 1000-bot sweep from one workstation hits **429** immediately regardless of concurrency 20 vs 1000.
2. **`/users/public/onboard` returned 400** for load-test phones (`999xxxxxxx`) — likely validation, duplicate phone, or engagement constraints; needs follow-up with a dedicated load-test engagement code on staging.
3. **`LOAD_TEST_RATE_LIMIT_RELAXED=true`** (implemented in this branch) must be set on the staging API **before** a meaningful success-rate soak. Re-run:

   ```bash
   # On staging host after deploy + env flag
   python scripts/staging_business_load_test.py --yes --max-bots 1000 --ramp 200 --ramp-sweeps \
     --sink-rate 0.02 --bypass-otp "$BYPASS_OTP" --report docs/ops/load_test_report.json
   ```

## DB / pool (local `.env` snapshot when available)

- `pg_stat_activity_count`: 1 (local probe only; not staging server)
- Notification status histogram (last 2h): empty from local DB

On staging host during soak, monitor:

- `pg_stat_activity` vs `DATABASE_POOL_SIZE` (default 5)
- `notifications` by `status` / `service_key`
- `integration_sync_logs` SMTP / WhatAPI errors

## Admin E2E

- `npm run test:e2e` (Playwright `e2e/notifications/*`) — **blocked** first on missing Chromium; after `npx playwright install chromium`, tests require **employee login** on `staging-admin.supershyft.com` (see `e2e/helpers/adminLogin.ts`).
- `scripts/staging_notification_e2e.py --yes` — run **on the staging API server** (needs DB + cron modules).

## Recommendations

1. Deploy this branch to staging; set `LOAD_TEST_RATE_LIMIT_RELAXED=true` for the soak window only.
2. Create a **dedicated load-test engagement** and point onboard scenario at `POST /users/code/{code}/onboard`.
3. Re-run 1000-bot soak with `--ramp-sweeps` (50 → 200 → 500 → 1000) once limits are relaxed.
4. Skip placeholder email OTP in production/staging after deploy — eliminates false-positive “sent” rows for `@example.com` profiles.