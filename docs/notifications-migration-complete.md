# Notifications migration complete (n8n → direct send)

## Summary

- WhatsApp and email content live in `notification_services` (template/email fields).
- Platform routing uses `notification_events` (event_code × recipient_type) via admin **Notifications** wizard.
- Per-engagement overrides use `engagement_notifications` with `recipient_type`.
- Delivery uses WhatAPI POST + SMTP with `queue_id` and webhook status updates.

## Support query alerts

`default_support_query_notification` in platform settings remains a comma-separated list of service keys for legacy support routing. Prefer a platform binding for `support_query_raised` when configured.

## Rollback

1. Restore `dev-api/n8n/workflows/` from git history.
2. Set `NOTIFICATION_USE_DIRECT_SEND=false` and re-add n8n base URL env vars if a temporary n8n path is reintroduced.
3. Re-run `scripts/backfill_notification_services_from_n8n.py` from git history if service content must be rebuilt from workflows.

## Legacy callback

`POST /notifications/callback` remains for manual or grace-period n8n callbacks; new sends should not depend on it.
