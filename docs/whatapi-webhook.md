# WhatAPI inbound webhook (manual setup)

Register your public API URL with WhatAPI so delivery events update `notifications.queue_id` rows.

## Verify URL (GET)

WhatAPI may call:

```
GET https://<api-host>/webhooks/whatapi?echo=true&challange=<token>
```

The API responds with plain text body equal to the challenge value.

Optional: set `WHATAPI_WEBHOOK_VERIFY_TOKEN` and pass `hub.verify_token` if WhatAPI sends Meta-style verify params.

## Event URL (POST)

```
POST https://<api-host>/webhooks/whatapi
```

Payload should include a `queue_id` (or nested under `message`) and a status/event field (`sent`, `delivered`, `read`, `failed`, `deleted`). Events without `queue_id` are logged only.

## WhatAPI dashboard

Use WhatAPI v2 webhook admin (`POST {{base-url}}/v2/webhook`) to point at the POST URL above. This is not automated in CI.
