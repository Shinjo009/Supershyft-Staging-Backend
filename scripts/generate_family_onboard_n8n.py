"""Generate n8n workflow JSON for family-onboard Diwali gift notifications."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "n8n" / "workflows"


def _uid() -> str:
    return str(uuid.uuid4())


def _wa_workflow(
    *,
    filename: str,
    path: str,
    webhook_name: str,
    prepare_js: str,
    sticky: str,
) -> None:
    nodes = [
        {
            "parameters": {"content": sticky, "height": 420, "width": 2200},
            "type": "n8n-nodes-base.stickyNote",
            "position": [4400, 4800],
            "typeVersion": 1,
            "id": _uid(),
            "name": "Sticky Note",
        },
        {
            "parameters": {"httpMethod": "POST", "path": path, "options": {}},
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2.1,
            "position": [4600, 5000],
            "id": _uid(),
            "name": webhook_name,
            "webhookId": _uid(),
        },
        {
            "parameters": {
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "strict",
                        "version": 3,
                    },
                    "conditions": [
                        {
                            "id": "1",
                            "leftValue": "={{ $json.body.notification_id }}",
                            "rightValue": 0,
                            "operator": {
                                "type": "number",
                                "operation": "exists",
                                "singleValue": True,
                            },
                        },
                        {
                            "id": "2",
                            "leftValue": "={{ $json.body.members }}",
                            "rightValue": "",
                            "operator": {
                                "type": "array",
                                "operation": "exists",
                                "singleValue": True,
                            },
                        },
                        {
                            "id": "3",
                            "leftValue": "={{ $json.body.participant_details }}",
                            "rightValue": "",
                            "operator": {
                                "type": "object",
                                "operation": "exists",
                                "singleValue": True,
                            },
                        },
                    ],
                    "combinator": "and",
                },
                "options": {},
            },
            "type": "n8n-nodes-base.if",
            "typeVersion": 2.3,
            "position": [4800, 5000],
            "id": _uid(),
            "name": "Validate Payload",
        },
        {
            "parameters": {
                "jsCode": (
                    "const body = $input.first().json.body;\n"
                    "const notificationId = body.notification_id;\n"
                    "const pd = body.participant_details || {};\n"
                    "return body.members.map(member => ({\n"
                    "  json: {\n"
                    "    notification_id: notificationId,\n"
                    "    first_name: member.first_name || '',\n"
                    "    last_name: member.last_name || '',\n"
                    "    email: member.email || '',\n"
                    "    phone: member.phone || '',\n"
                    "    participant_details: pd\n"
                    "  }\n"
                    "}));"
                ),
            },
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [5020, 4880],
            "id": _uid(),
            "name": "Split Members",
        },
        {
            "parameters": {"mode": "runOnceForEachItem", "jsCode": prepare_js},
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [5240, 4880],
            "id": _uid(),
            "name": "Prepare WhatsApp",
        },
        {
            "parameters": {
                "url": "https://webhook.whatapi.in/webhook/REPLACE_WHATAPI_TOKEN",
                "sendQuery": True,
                "queryParameters": {
                    "parameters": [
                        {"name": "number", "value": "={{ $json.phone }}"},
                        {"name": "message", "value": "={{ $json.message }}"},
                    ]
                },
                "options": {},
            },
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.4,
            "position": [5460, 4880],
            "id": _uid(),
            "name": "Send WhatsApp",
            "retryOnFail": True,
            "waitBetweenTries": 3000,
            "onError": "continueErrorOutput",
        },
        {
            "parameters": {
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "strict",
                        "version": 2,
                    },
                    "conditions": [
                        {
                            "id": "a",
                            "leftValue": "={{ $json.accepted }}",
                            "rightValue": "",
                            "operator": {
                                "type": "boolean",
                                "operation": "true",
                                "singleValue": True,
                            },
                        }
                    ],
                    "combinator": "and",
                },
                "options": {},
            },
            "type": "n8n-nodes-base.if",
            "typeVersion": 2.3,
            "position": [5680, 4760],
            "id": _uid(),
            "name": "WhatAPI Accepted?",
        },
        {
            "parameters": {
                "assignments": {
                    "assignments": [
                        {
                            "id": "1",
                            "name": "notification_id",
                            "value": "={{ $('Prepare WhatsApp').item.json.notification_id }}",
                            "type": "number",
                        },
                        {"id": "2", "name": "status", "value": "sent", "type": "string"},
                        {
                            "id": "3",
                            "name": "message",
                            "value": "Message sent successfully",
                            "type": "string",
                        },
                    ]
                },
                "options": {},
            },
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [5900, 4680],
            "id": _uid(),
            "name": "WhatsApp Sent",
        },
        {
            "parameters": {
                "assignments": {
                    "assignments": [
                        {
                            "id": "1",
                            "name": "notification_id",
                            "value": f"={{ $('{webhook_name}').item.json.body.notification_id }}",
                            "type": "number",
                        },
                        {"id": "2", "name": "status", "value": "failed", "type": "string"},
                        {
                            "id": "3",
                            "name": "message",
                            "value": "WhatsApp sending failed",
                            "type": "string",
                        },
                    ]
                },
                "options": {},
            },
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [5900, 4920],
            "id": _uid(),
            "name": "WhatsApp Failed",
        },
        {
            "parameters": {
                "assignments": {
                    "assignments": [
                        {
                            "id": "1",
                            "name": "notification_id",
                            "value": f"={{ $('{webhook_name}').item.json.body.notification_id }}",
                            "type": "number",
                        },
                        {"id": "2", "name": "status", "value": "failed", "type": "string"},
                        {
                            "id": "3",
                            "name": "message",
                            "value": "Payload validation failed",
                            "type": "string",
                        },
                    ]
                },
                "options": {},
            },
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [5020, 5120],
            "id": _uid(),
            "name": "Validation Failed",
        },
        {
            "parameters": {
                "method": "POST",
                "url": "https://api.supershyft.com/notifications/callback",
                "authentication": "genericCredentialType",
                "genericAuthType": "httpHeaderAuth",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": (
                    "={\n"
                    '  "notification_id": {{ $json.notification_id }},\n'
                    '  "status": "{{ $json.status }}",\n'
                    '  "message": "{{ $json.message }}"\n'
                    "}"
                ),
                "options": {},
            },
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.4,
            "position": [6120, 5000],
            "id": _uid(),
            "name": "Callback",
            "alwaysOutputData": True,
            "retryOnFail": True,
            "credentials": {
                "httpHeaderAuth": {
                    "id": "djiMPtATquR2OnRc",
                    "name": "Notification Header Auth | api.supershyft",
                }
            },
            "onError": "continueRegularOutput",
        },
    ]
    connections = {
        webhook_name: {
            "main": [[{"node": "Validate Payload", "type": "main", "index": 0}]]
        },
        "Validate Payload": {
            "main": [
                [{"node": "Split Members", "type": "main", "index": 0}],
                [{"node": "Validation Failed", "type": "main", "index": 0}],
            ]
        },
        "Split Members": {
            "main": [[{"node": "Prepare WhatsApp", "type": "main", "index": 0}]]
        },
        "Prepare WhatsApp": {
            "main": [[{"node": "Send WhatsApp", "type": "main", "index": 0}]]
        },
        "Send WhatsApp": {
            "main": [
                [{"node": "WhatAPI Accepted?", "type": "main", "index": 0}],
                [{"node": "WhatsApp Failed", "type": "main", "index": 0}],
            ]
        },
        "WhatAPI Accepted?": {
            "main": [
                [{"node": "WhatsApp Sent", "type": "main", "index": 0}],
                [{"node": "WhatsApp Failed", "type": "main", "index": 0}],
            ]
        },
        "WhatsApp Sent": {"main": [[{"node": "Callback", "type": "main", "index": 0}]]},
        "WhatsApp Failed": {"main": [[{"node": "Callback", "type": "main", "index": 0}]]},
        "Validation Failed": {"main": [[{"node": "Callback", "type": "main", "index": 0}]]},
    }
    payload = {
        "nodes": nodes,
        "connections": connections,
        "pinData": {},
        "meta": {"instanceId": _uid()},
    }
    (OUT / filename).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _email_workflow(
    *,
    filename: str,
    path: str,
    webhook_name: str,
    prepare_js: str,
    sticky: str,
) -> None:
    nodes = [
        {
            "parameters": {"content": sticky, "height": 420, "width": 2200},
            "type": "n8n-nodes-base.stickyNote",
            "position": [4400, 2600],
            "typeVersion": 1,
            "id": _uid(),
            "name": "Sticky Note",
        },
        {
            "parameters": {"httpMethod": "POST", "path": path, "options": {}},
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2.1,
            "position": [4600, 2800],
            "id": _uid(),
            "name": webhook_name,
            "webhookId": _uid(),
        },
        {
            "parameters": {
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "strict",
                        "version": 3,
                    },
                    "conditions": [
                        {
                            "id": "1",
                            "leftValue": "={{ $json.body.notification_id }}",
                            "rightValue": 0,
                            "operator": {
                                "type": "number",
                                "operation": "exists",
                                "singleValue": True,
                            },
                        },
                        {
                            "id": "2",
                            "leftValue": "={{ $json.body.members }}",
                            "rightValue": "",
                            "operator": {
                                "type": "array",
                                "operation": "exists",
                                "singleValue": True,
                            },
                        },
                        {
                            "id": "3",
                            "leftValue": "={{ $json.body.participant_details }}",
                            "rightValue": "",
                            "operator": {
                                "type": "object",
                                "operation": "exists",
                                "singleValue": True,
                            },
                        },
                    ],
                    "combinator": "and",
                },
                "options": {},
            },
            "type": "n8n-nodes-base.if",
            "typeVersion": 2.3,
            "position": [4800, 2800],
            "id": _uid(),
            "name": "Validate Payload",
        },
        {
            "parameters": {
                "jsCode": (
                    "const body = $input.first().json.body;\n"
                    "const notificationId = body.notification_id;\n"
                    "const pd = body.participant_details || {};\n"
                    "return body.members.map(member => ({\n"
                    "  json: {\n"
                    "    notification_id: notificationId,\n"
                    "    first_name: member.first_name || '',\n"
                    "    last_name: member.last_name || '',\n"
                    "    email: member.email || '',\n"
                    "    phone: member.phone || '',\n"
                    "    participant_details: pd\n"
                    "  }\n"
                    "}));"
                ),
            },
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [5020, 2680],
            "id": _uid(),
            "name": "Split Members",
        },
        {
            "parameters": {"mode": "runOnceForEachItem", "jsCode": prepare_js},
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [5240, 2680],
            "id": _uid(),
            "name": "Prepare Email",
        },
        {
            "parameters": {
                "fromEmail": "support@supershyft.com",
                "toEmail": "={{ $json.to }}",
                "subject": "={{ $json.subject }}",
                "emailFormat": "text",
                "text": "={{ $json.body }}",
                "options": {"appendAttribution": False},
            },
            "type": "n8n-nodes-base.emailSend",
            "typeVersion": 2.1,
            "position": [5460, 2680],
            "id": _uid(),
            "name": "Send Email",
            "retryOnFail": True,
            "waitBetweenTries": 3000,
            "credentials": {"smtp": {"id": "eCub7Y6RwBvqnurK", "name": "SMTP account"}},
            "onError": "continueErrorOutput",
        },
        {
            "parameters": {
                "assignments": {
                    "assignments": [
                        {
                            "id": "1",
                            "name": "notification_id",
                            "value": "={{ $('Prepare Email').item.json.notification_id }}",
                            "type": "number",
                        },
                        {"id": "2", "name": "status", "value": "sent", "type": "string"},
                        {
                            "id": "3",
                            "name": "message",
                            "value": "Email sent successfully",
                            "type": "string",
                        },
                    ]
                },
                "options": {},
            },
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [5680, 2600],
            "id": _uid(),
            "name": "Email Sent",
        },
        {
            "parameters": {
                "assignments": {
                    "assignments": [
                        {
                            "id": "1",
                            "name": "notification_id",
                            "value": f"={{ $('{webhook_name}').item.json.body.notification_id }}",
                            "type": "number",
                        },
                        {"id": "2", "name": "status", "value": "failed", "type": "string"},
                        {
                            "id": "3",
                            "name": "message",
                            "value": "Email sending failed",
                            "type": "string",
                        },
                    ]
                },
                "options": {},
            },
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [5680, 2840],
            "id": _uid(),
            "name": "Email Failed",
        },
        {
            "parameters": {
                "assignments": {
                    "assignments": [
                        {
                            "id": "1",
                            "name": "notification_id",
                            "value": f"={{ $('{webhook_name}').item.json.body.notification_id }}",
                            "type": "number",
                        },
                        {"id": "2", "name": "status", "value": "failed", "type": "string"},
                        {
                            "id": "3",
                            "name": "message",
                            "value": "Payload validation failed",
                            "type": "string",
                        },
                    ]
                },
                "options": {},
            },
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [5020, 2960],
            "id": _uid(),
            "name": "Validation Failed",
        },
        {
            "parameters": {
                "method": "POST",
                "url": "https://api.supershyft.com/notifications/callback",
                "authentication": "genericCredentialType",
                "genericAuthType": "httpHeaderAuth",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": (
                    "={\n"
                    '  "notification_id": {{ $json.notification_id }},\n'
                    '  "status": "{{ $json.status }}",\n'
                    '  "message": "{{ $json.message }}"\n'
                    "}"
                ),
                "options": {},
            },
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.4,
            "position": [5900, 2840],
            "id": _uid(),
            "name": "Callback",
            "alwaysOutputData": True,
            "retryOnFail": True,
            "credentials": {
                "httpHeaderAuth": {
                    "id": "djiMPtATquR2OnRc",
                    "name": "Notification Header Auth | api.supershyft",
                }
            },
            "onError": "continueRegularOutput",
        },
    ]
    connections = {
        webhook_name: {
            "main": [[{"node": "Validate Payload", "type": "main", "index": 0}]]
        },
        "Validate Payload": {
            "main": [
                [{"node": "Split Members", "type": "main", "index": 0}],
                [{"node": "Validation Failed", "type": "main", "index": 0}],
            ]
        },
        "Split Members": {
            "main": [[{"node": "Prepare Email", "type": "main", "index": 0}]]
        },
        "Prepare Email": {"main": [[{"node": "Send Email", "type": "main", "index": 0}]]},
        "Send Email": {
            "main": [
                [{"node": "Email Sent", "type": "main", "index": 0}],
                [{"node": "Email Failed", "type": "main", "index": 0}],
            ]
        },
        "Email Sent": {"main": [[{"node": "Callback", "type": "main", "index": 0}]]},
        "Email Failed": {"main": [[{"node": "Callback", "type": "main", "index": 0}]]},
        "Validation Failed": {"main": [[{"node": "Callback", "type": "main", "index": 0}]]},
    }
    payload = {
        "nodes": nodes,
        "connections": connections,
        "pinData": {},
        "meta": {"instanceId": _uid()},
    }
    (OUT / filename).write_text(json.dumps(payload, indent=2), encoding="utf-8")


SENDER_WA_JS = r"""const item = $input.item.json;
const pd = item.participant_details || {};
const bookerName = (pd.booker_name || item.first_name || 'there').trim();
const recipientName = (pd.recipient_name || '-').trim();
const relationship = (pd.relationship || '-').trim();
const giftUrl = (pd.gift_url || 'https://app.supershyft.com').trim();
let phone = String(item.phone || '').replace(/\D/g, '');
if (phone.length === 10) phone = '91' + phone;
const message = `REPLACE_SENDER_TEMPLATE,${bookerName},${recipientName},${relationship},${giftUrl}`;
return { json: { notification_id: item.notification_id, phone, message } };"""

RECEIVER_WA_JS = r"""const item = $input.item.json;
const pd = item.participant_details || {};
const recipientName = (pd.recipient_name || item.first_name || 'there').trim();
const bookerName = (pd.booker_name || '-').trim();
const giftUrl = (pd.gift_url || 'https://app.supershyft.com').trim();
let phone = String(item.phone || '').replace(/\D/g, '');
if (phone.length === 10) phone = '91' + phone;
const message = `REPLACE_RECEIVER_TEMPLATE,${recipientName},${bookerName},${giftUrl}`;
return { json: { notification_id: item.notification_id, phone, message } };"""

SENDER_EMAIL_JS = r"""const item = $input.item.json;
const pd = item.participant_details || {};
const bookerName = (pd.booker_name || item.first_name || 'there').trim();
const recipientName = (pd.recipient_name || '-').trim();
const relationship = (pd.relationship || '-').trim();
const giftUrl = (pd.gift_url || 'https://app.supershyft.com').trim();
const body = `Hello ${bookerName},

This Diwali you are giving someone you love something truly special through the gift of health and well being.

Your personalised BIO AI Wellness Assessment for ${recipientName} is being created with love.

Recipient Name: ${recipientName}
Relationship: ${relationship}

Because the people we love deserve a healthier and happier life with many more beautiful moments together.

You can check the details below for your convenience.

${giftUrl}

Thank you for choosing to make someone's well being a little more special this Diwali.

Wishing you and your family a beautiful Diwali filled with love happiness and good health.

Warm regards
Team Supershyft`;
return { json: { notification_id: item.notification_id, to: item.email, subject: 'Your Diwali gift of health from Supershyft', body } };"""

RECEIVER_EMAIL_JS = r"""const item = $input.item.json;
const pd = item.participant_details || {};
const recipientName = (pd.recipient_name || item.first_name || 'there').trim();
const bookerName = (pd.booker_name || '-').trim();
const giftUrl = (pd.gift_url || 'https://app.supershyft.com').trim();
const body = `Hello ${recipientName},

This Diwali we have a little surprise for you from someone who cares about you deeply.

${bookerName} has chosen to gift you a personalised BIO AI Wellness Assessment because they want you to prioritise your health and take a little time for yourself.

Life gets busy with work family and everything in between and sometimes we forget to look after ourselves.

This gift is a gentle reminder that your health matters and that the people who love you want to see you happy healthy and around for many more Diwalis together.

Through personalised BIO AI insights you can learn more about your health and discover recommendations to help you make informed choices for your well being.

Your special gift is waiting for you here.

${giftUrl}

We hope this little gesture brings a smile to your face and reminds you how deeply you are loved.

Wishing you and your family a Diwali filled with good health happiness and beautiful moments together.

With warmth and love

Team Supershyft`;
return { json: { notification_id: item.notification_id, to: item.email, subject: 'A special Diwali gift for you from Supershyft', body } };"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    _wa_workflow(
        filename="family-onboard-sender-whatsapp.json",
        path="family-onboard-sender-whatsapp-v1",
        webhook_name="Family Onboard Sender WhatsApp",
        prepare_js=SENDER_WA_JS,
        sticky=(
            "## Family Onboard Gift — Sender WhatsApp\n"
            "Replace REPLACE_SENDER_TEMPLATE with your approved WhatAPI template id (campXX).\n"
            "Replace REPLACE_WHATAPI_TOKEN in Send WhatsApp node.\n"
            "Slots: {{1}} booker, {{2}} recipient, {{3}} relationship, {{4}} gift URL."
        ),
    )
    _wa_workflow(
        filename="family-onboard-receiver-whatsapp.json",
        path="family-onboard-receiver-whatsapp-v1",
        webhook_name="Family Onboard Receiver WhatsApp",
        prepare_js=RECEIVER_WA_JS,
        sticky=(
            "## Family Onboard Gift — Receiver WhatsApp\n"
            "Replace REPLACE_RECEIVER_TEMPLATE with your approved WhatAPI template id.\n"
            "Replace REPLACE_WHATAPI_TOKEN in Send WhatsApp node.\n"
            "Slots: {{1}} recipient, {{2}} booker, {{3}} gift URL."
        ),
    )
    _email_workflow(
        filename="family-onboard-sender-email.json",
        path="family-onboard-sender-email-v1",
        webhook_name="Family Onboard Sender Email",
        prepare_js=SENDER_EMAIL_JS,
        sticky="## Family Onboard Gift — Sender Email (Diwali copy in Prepare Email node)",
    )
    _email_workflow(
        filename="family-onboard-receiver-email.json",
        path="family-onboard-receiver-email-v1",
        webhook_name="Family Onboard Receiver Email",
        prepare_js=RECEIVER_EMAIL_JS,
        sticky="## Family Onboard Gift — Receiver Email (Diwali copy in Prepare Email node)",
    )
    print("Wrote 4 workflows to", OUT)


if __name__ == "__main__":
    main()
