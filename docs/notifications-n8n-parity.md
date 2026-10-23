# Notification content parity with n8n (e543900)

Direct WhatsApp/email send reads `notification_services.template_name` and `template_variables` parsed from n8n workflows at git ref **`e543900`** (`n8n/workflows/*.json`). Chained `POST /notifications/dispatch` nodes in n8n are **not** replayed by a single service dispatch.

## Regenerate fixtures

From `dev-api`:

```bash
PYTHONPATH=. python scripts/generate_notification_fixtures_from_n8n.py
```

Outputs:

- `db/fixtures/notification_services_content.json` — UPSERT source for migrations
- `db/fixtures/n8n_workflow_service_map.json` — webhook → service_key, template, chained dispatches (informational)
- Warnings when `len(template_variables)` ≠ WABA body param count in `templates-json-simple.json`

Manual fixes: `db/fixtures/notification_services_overrides.json` (webhook aliases, composite splits, deprecated keys).

## Deprecated composite keys

`booking-alert-email+whatsapp+participant-welcome-metsights` is inactive. Use:

- `booking-alert-whatsapp-metsights`
- `booking-alert-email-metsights`
- `welcome-whatsapp-metsights` (event-driven welcome; was n8n chain target)

## Migration

Alembic `0185_n8n_template_parity` UPSERTs all rows from `notification_services_content.json`.

## Staging E2E (all active services → test phone)

In `dev-admin`:

```bash
STAGING_EMPLOYEE_PHONE=8762830757 STAGING_BYPASS_OTP=654321 npm run test:e2e:staging:notifications
```

Optional: `STAGING_API_URL`, `STAGING_ADMIN_URL`, `STAGING_TEST_USER_ID` (defaults to onboarding a participant at `STAGING_EMPLOYEE_PHONE` if missing). Payload hints: `e2e/fixtures/notification-dispatch-hints.json`.
