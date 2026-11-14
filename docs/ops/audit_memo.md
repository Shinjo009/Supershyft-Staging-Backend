# Staging notification audit memo (Nov 2026)

## Themes since `cb98148` / `691abf0`

- Notification platform: bindings engine, direct WhatAPI/SMTP, wizard APIs, engagement notification setup.
- HTTP **BackgroundTasks** deferral for outbound delivery (`NOTIFICATION_DEFER_HTTP_DELIVERY`).
- Admin: notification logs/services/bindings, binding wizard, WhatsApp template header preview.
- OTP dual-channel (`notify_all_channels`) on phone `send-otp`.

## Hygiene removed / archived

| Item | Action |
|------|--------|
| `fix_user.py` | Deleted (unsafe mass user profile updates). |
| `scripts/debug_whatsapp_template_lookup.py` | Deleted. |
| Workspace `tmp_*.py` | Deleted locally (untracked). |
| `scripts/staging_*_cleanup.sql` | Moved to `docs/ops/archive/` (do not re-run blindly). |

**Kept:** `scripts/staging_notification_e2e.py`, `scripts/staging_whatsapp_e2e.py`.

## Bugs addressed

1. **Placeholder emails** (`@example.com`, etc.): `NotificationEngine` skips email-channel services when no deliverable address (avoids false SMTP “sent” for user 14446-style profiles).
2. **Deferred dispatch failures:** `_execute_deliver_job` marks notification `failed` with message on unhandled exceptions (avoids stuck `pending`).
3. **Load test rate limits:** `LOAD_TEST_RATE_LIMIT_RELAXED` raises `/auth/send-otp` and `/auth/resend-otp` limits on staging during soak.

## New tooling

- `scripts/staging_business_load_test.py` — fake contacts, sink sampling, BYPASS_OTP verify, optional DB metrics/cleanup.
- `modules/notifications/deliverable_contact.py` — shared email deliverability heuristic.

## Follow-ups (not in this pass)

- Redis/queue workers instead of BackgroundTasks.
- Release DB session before long SMTP/WhatAPI calls if soak shows pool exhaustion.
- Extend OTP API `channels` to list **attempted** dual-channel emits (product decision).