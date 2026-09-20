"""One-off generator for phlebo n8n workflow JSON files."""

from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "n8n" / "workflows"
META = {
    "instanceId": "eed8b3457b986f6362867dfc9a5378439da2846ec92ad64fddac97c84b5cba32"
}


def _wa_conditions(prefix: str, *, require_session: bool, path: str) -> list[dict]:
    conditions = [
        {
            "id": f"{prefix}-cond-notif",
            "leftValue": "={{ $json.body.notification_id }}",
            "rightValue": 0,
            "operator": {"type": "number", "operation": "exists", "singleValue": True},
        },
        {
            "id": f"{prefix}-cond-members",
            "leftValue": "={{ $json.body.members }}",
            "rightValue": "",
            "operator": {"type": "array", "operation": "exists", "singleValue": True},
        },
        {
            "id": f"{prefix}-cond-len",
            "leftValue": "={{ $json.body.members.length }}",
            "rightValue": 0,
            "operator": {"type": "number", "operation": "gt"},
        },
        {
            "id": f"{prefix}-cond-pd",
            "leftValue": "={{ $json.body.participant_details }}",
            "rightValue": "",
            "operator": {"type": "object", "operation": "exists", "singleValue": True},
        },
        {
            "id": f"{prefix}-cond-phlebo",
            "leftValue": "={{ $json.body.participant_details.phlebo_name }}",
            "rightValue": "",
            "operator": {"type": "string", "operation": "exists", "singleValue": True},
        },
    ]
    if require_session:
        conditions.extend(
            [
                {
                    "id": f"{prefix}-cond-sd",
                    "leftValue": "={{ $json.body.members[0].session_details }}",
                    "rightValue": "",
                    "operator": {"type": "object", "operation": "exists", "singleValue": True},
                },
                {
                    "id": f"{prefix}-cond-date",
                    "leftValue": "={{ $json.body.members[0].session_details.date }}",
                    "rightValue": "",
                    "operator": {"type": "string", "operation": "exists", "singleValue": True},
                },
                {
                    "id": f"{prefix}-cond-slot",
                    "leftValue": "={{ $json.body.members[0].session_details.slot }}",
                    "rightValue": "",
                    "operator": {"type": "string", "operation": "exists", "singleValue": True},
                },
            ]
        )
    elif "enroute" in path:
        conditions.append(
            {
                "id": f"{prefix}-cond-track",
                "leftValue": "={{ $json.body.participant_details.tracking_url }}",
                "rightValue": "",
                "operator": {"type": "string", "operation": "exists", "singleValue": True},
            }
        )
    elif "delay" in path:
        conditions.append(
            {
                "id": f"{prefix}-cond-eta",
                "leftValue": "={{ $json.body.participant_details.eta_in_minutes }}",
                "rightValue": 0,
                "operator": {"type": "number", "operation": "exists", "singleValue": True},
            }
        )
    return conditions


SPLIT_JS = """const body = $input.first().json.body;
const notificationId = body.notification_id;
const pd = body.participant_details || {};

return body.members.map((member) => ({
  json: {
    notification_id: notificationId,
    first_name: member.first_name || 'Participant',
    last_name: member.last_name || '',
    email: member.email || '',
    phone: member.phone || '',
    participant_details: pd,
    session_details: member.session_details || null
  }
}));"""


def wa_workflow(
    *,
    prefix: str,
    title: str,
    path: str,
    webhook_id: str,
    sticky: str,
    require_session: bool,
    prepare_js: str,
    validate_msg: str,
) -> dict:
    prepare_name = f"Prepare {title}"
    nodes = [
        {
            "parameters": {"content": sticky, "height": 640, "width": 2336},
            "type": "n8n-nodes-base.stickyNote",
            "position": [4448, 4800],
            "typeVersion": 1,
            "id": f"{prefix}-sticky",
            "name": f"Sticky Note {title}",
        },
        {
            "parameters": {"httpMethod": "POST", "path": path, "options": {}},
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2.1,
            "position": [4576, 4992],
            "id": f"{prefix}-webhook",
            "name": title,
            "webhookId": webhook_id,
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
                    "conditions": _wa_conditions(prefix, require_session=require_session, path=path),
                    "combinator": "and",
                },
                "options": {},
            },
            "type": "n8n-nodes-base.if",
            "typeVersion": 2.3,
            "position": [4784, 4992],
            "id": f"{prefix}-validate",
            "name": "Validate WhatsApp Payload",
        },
        {
            "parameters": {"jsCode": SPLIT_JS},
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [5008, 4880],
            "id": f"{prefix}-split",
            "name": "Split Members",
        },
        {
            "parameters": {"mode": "runOnceForEachItem", "jsCode": prepare_js},
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [5264, 4880],
            "id": f"{prefix}-prepare",
            "name": prepare_name,
        },
        {
            "parameters": {
                "url": "https://webhook.whatapi.in/webhook/6a057e696f1a8bf9dd523d1f",
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
            "position": [5488, 4880],
            "id": f"{prefix}-send",
            "name": "Send WhatsApp Message",
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
                            "id": f"{prefix}-accepted",
                            "leftValue": "={{ $json.accepted }}",
                            "rightValue": "",
                            "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                        }
                    ],
                    "combinator": "and",
                },
                "options": {},
            },
            "type": "n8n-nodes-base.if",
            "typeVersion": 2.3,
            "position": [5712, 4768],
            "id": f"{prefix}-accepted",
            "name": "WhatAPI Accepted?",
        },
        {
            "parameters": {
                "assignments": {
                    "assignments": [
                        {
                            "id": f"{prefix}-sent-id",
                            "name": "notification_id",
                            "value": f"={{{{ $('{prepare_name}').item.json.notification_id }}}}",
                            "type": "number",
                        },
                        {"id": f"{prefix}-sent-status", "name": "status", "value": "sent", "type": "string"},
                        {
                            "id": f"{prefix}-sent-msg",
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
            "position": [6208, 4688],
            "id": f"{prefix}-sent",
            "name": "WhatsApp Sent Response",
        },
        {
            "parameters": {
                "assignments": {
                    "assignments": [
                        {
                            "id": f"{prefix}-fail-id",
                            "name": "notification_id",
                            "value": f"={{{{ $('{prepare_name}').item.json.notification_id }}}}",
                            "type": "number",
                        },
                        {"id": f"{prefix}-fail-status", "name": "status", "value": "failed", "type": "string"},
                        {
                            "id": f"{prefix}-fail-msg",
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
            "position": [5808, 4960],
            "id": f"{prefix}-failed",
            "name": "WhatsApp Failed Response",
        },
        {
            "parameters": {
                "assignments": {
                    "assignments": [
                        {
                            "id": f"{prefix}-na-id",
                            "name": "notification_id",
                            "value": f"={{{{ $('{prepare_name}').item.json.notification_id }}}}",
                            "type": "number",
                        },
                        {"id": f"{prefix}-na-status", "name": "status", "value": "failed", "type": "string"},
                        {
                            "id": f"{prefix}-na-msg",
                            "name": "message",
                            "value": "WhatsApp sending failed: message not accepted",
                            "type": "string",
                        },
                    ]
                },
                "options": {},
            },
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [6032, 4864],
            "id": f"{prefix}-notaccepted",
            "name": "WhatAPI Not Accepted",
        },
        {
            "parameters": {
                "assignments": {
                    "assignments": [
                        {
                            "id": f"{prefix}-val-id",
                            "name": "notification_id",
                            "value": f"={{{{ $('{title}').item.json.body.notification_id }}}}",
                            "type": "number",
                        },
                        {"id": f"{prefix}-val-status", "name": "status", "value": "failed", "type": "string"},
                        {"id": f"{prefix}-val-msg", "name": "message", "value": validate_msg, "type": "string"},
                    ]
                },
                "options": {},
            },
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [5008, 5136],
            "id": f"{prefix}-valfail",
            "name": "WhatsApp Validation Failed",
        },
        {
            "parameters": {
                "method": "POST",
                "url": "https://api.supershyft.com/notifications/callback",
                "authentication": "genericCredentialType",
                "genericAuthType": "httpHeaderAuth",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": '={\n  "notification_id": {{ $json.notification_id }},\n  "status": "{{ $json.status }}",\n  "message": "{{ $json.message }}"\n}',
                "options": {},
            },
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.4,
            "position": [6576, 5152],
            "id": f"{prefix}-callback",
            "name": "WhatsApp Callback",
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
        title: {"main": [[{"node": "Validate WhatsApp Payload", "type": "main", "index": 0}]]},
        "Validate WhatsApp Payload": {
            "main": [
                [{"node": "Split Members", "type": "main", "index": 0}],
                [{"node": "WhatsApp Validation Failed", "type": "main", "index": 0}],
            ]
        },
        "Split Members": {"main": [[{"node": prepare_name, "type": "main", "index": 0}]]},
        prepare_name: {"main": [[{"node": "Send WhatsApp Message", "type": "main", "index": 0}]]},
        "Send WhatsApp Message": {
            "main": [
                [{"node": "WhatAPI Accepted?", "type": "main", "index": 0}],
                [{"node": "WhatsApp Failed Response", "type": "main", "index": 0}],
            ]
        },
        "WhatAPI Accepted?": {
            "main": [
                [{"node": "WhatsApp Sent Response", "type": "main", "index": 0}],
                [{"node": "WhatAPI Not Accepted", "type": "main", "index": 0}],
            ]
        },
        "WhatsApp Sent Response": {"main": [[{"node": "WhatsApp Callback", "type": "main", "index": 0}]]},
        "WhatsApp Failed Response": {"main": [[{"node": "WhatsApp Callback", "type": "main", "index": 0}]]},
        "WhatAPI Not Accepted": {"main": [[{"node": "WhatsApp Callback", "type": "main", "index": 0}]]},
        "WhatsApp Validation Failed": {"main": [[{"node": "WhatsApp Callback", "type": "main", "index": 0}]]},
    }
    return {"nodes": nodes, "connections": connections, "pinData": {}, "meta": META}


def email_workflow(
    *,
    prefix: str,
    title: str,
    path: str,
    webhook_id: str,
    sticky: str,
    require_session: bool,
    prepare_js: str,
    validate_msg: str,
) -> dict:
    prepare_name = f"Prepare {title}"
    send_name = f"Send {title}"
    nodes = [
        {
            "parameters": {"content": sticky, "height": 560, "width": 1984},
            "type": "n8n-nodes-base.stickyNote",
            "position": [4432, 2528],
            "typeVersion": 1,
            "id": f"{prefix}-sticky",
            "name": f"Sticky Note {title}",
        },
        {
            "parameters": {"httpMethod": "POST", "path": path, "options": {}},
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2.1,
            "position": [4544, 2752],
            "id": f"{prefix}-webhook",
            "name": title,
            "webhookId": webhook_id,
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
                    "conditions": _wa_conditions(prefix, require_session=require_session, path=path),
                    "combinator": "and",
                },
                "options": {},
            },
            "type": "n8n-nodes-base.if",
            "typeVersion": 2.3,
            "position": [4784, 2752],
            "id": f"{prefix}-validate",
            "name": "Validate Email Payload",
        },
        {
            "parameters": {"jsCode": SPLIT_JS},
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [4992, 2640],
            "id": f"{prefix}-split",
            "name": "Split Members",
        },
        {
            "parameters": {"mode": "runOnceForEachItem", "jsCode": prepare_js},
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [5216, 2640],
            "id": f"{prefix}-prepare",
            "name": prepare_name,
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
            "position": [5456, 2640],
            "id": f"{prefix}-send",
            "name": send_name,
            "retryOnFail": True,
            "waitBetweenTries": 3000,
            "webhookId": f"{prefix}-smtp",
            "credentials": {"smtp": {"id": "eCub7Y6RwBvqnurK", "name": "SMTP account"}},
            "onError": "continueErrorOutput",
        },
        {
            "parameters": {
                "assignments": {
                    "assignments": [
                        {
                            "id": f"{prefix}-sent-id",
                            "name": "notification_id",
                            "value": f"={{{{ $('{prepare_name}').item.json.notification_id }}}}",
                            "type": "number",
                        },
                        {"id": f"{prefix}-sent-status", "name": "status", "value": "sent", "type": "string"},
                        {
                            "id": f"{prefix}-sent-msg",
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
            "position": [5696, 2560],
            "id": f"{prefix}-sent",
            "name": "Email Sent Response",
        },
        {
            "parameters": {
                "assignments": {
                    "assignments": [
                        {"id": f"{prefix}-fail-id", "name": "notification_id", "value": "={{ $json.notification_id }}", "type": "number"},
                        {"id": f"{prefix}-fail-status", "name": "status", "value": "failed", "type": "string"},
                        {"id": f"{prefix}-fail-msg", "name": "message", "value": "Email sending failed", "type": "string"},
                    ]
                },
                "options": {},
            },
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [5696, 2736],
            "id": f"{prefix}-fail",
            "name": "Email Failed Response",
        },
        {
            "parameters": {
                "assignments": {
                    "assignments": [
                        {
                            "id": f"{prefix}-val-id",
                            "name": "notification_id",
                            "value": f"={{{{ $('{title}').item.json.body.notification_id }}}}",
                            "type": "number",
                        },
                        {"id": f"{prefix}-val-status", "name": "status", "value": "failed", "type": "string"},
                        {"id": f"{prefix}-val-msg", "name": "message", "value": validate_msg, "type": "string"},
                    ]
                },
                "options": {},
            },
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [4992, 2880],
            "id": f"{prefix}-valfail",
            "name": "Email Validation Failed",
        },
        {
            "parameters": {
                "method": "POST",
                "url": "https://api.supershyft.com/notifications/callback",
                "authentication": "genericCredentialType",
                "genericAuthType": "httpHeaderAuth",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": '={\n  "notification_id": {{ $json.notification_id }},\n  "status": "{{ $json.status }}",\n  "message": "{{ $json.message }}"\n}',
                "options": {},
            },
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.4,
            "position": [6128, 2880],
            "id": f"{prefix}-callback",
            "name": "Email Callback",
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
        title: {"main": [[{"node": "Validate Email Payload", "type": "main", "index": 0}]]},
        "Validate Email Payload": {
            "main": [
                [{"node": "Split Members", "type": "main", "index": 0}],
                [{"node": "Email Validation Failed", "type": "main", "index": 0}],
            ]
        },
        "Split Members": {"main": [[{"node": prepare_name, "type": "main", "index": 0}]]},
        prepare_name: {"main": [[{"node": send_name, "type": "main", "index": 0}]]},
        send_name: {
            "main": [
                [{"node": "Email Sent Response", "type": "main", "index": 0}],
                [{"node": "Email Failed Response", "type": "main", "index": 0}],
            ]
        },
        "Email Sent Response": {"main": [[{"node": "Email Callback", "type": "main", "index": 0}]]},
        "Email Failed Response": {"main": [[{"node": "Email Callback", "type": "main", "index": 0}]]},
        "Email Validation Failed": {"main": [[{"node": "Email Callback", "type": "main", "index": 0}]]},
    }
    return {"nodes": nodes, "connections": connections, "pinData": {}, "meta": META}


ASSIGNED_WA = """const member = $input.item.json;
const name = (member.first_name || 'Participant').trim();
const pd = member.participant_details || {};
const sd = member.session_details || {};
const phleboName = (pd.phlebo_name || 'Phlebotomist').trim();
const collectionDate = (sd.date || '').trim();
const collectionTime = (sd.slot || '').trim();
const masked = (pd.masked_number || '').trim();
const tracking = (pd.tracking_url || '').trim();

let phone = String(member.phone || '').replace(/\\D/g, '');
if (phone.length === 10) phone = '91' + phone;

const maskedPart = masked ? `Contact: ${masked}` : '';
const trackingPart = tracking ? `Track: ${tracking}` : '';
const message = `camp17,${name},Your phlebotomist ${phleboName} has been assigned for your blood collection.,Date: ${collectionDate},Time: ${collectionTime},${maskedPart},${trackingPart},Please visit: app.supershyft.com,,Thanks for taking a moment to read this message.`;

return { json: { notification_id: member.notification_id, phone, message } };"""

REASSIGNED_WA = ASSIGNED_WA.replace("has been assigned", "has been reassigned")

ENROUTE_WA = """const member = $input.item.json;
const name = (member.first_name || 'Participant').trim();
const pd = member.participant_details || {};
const phleboName = (pd.phlebo_name || 'Phlebotomist').trim();
const masked = (pd.masked_number || '').trim();
const tracking = (pd.tracking_url || '').trim();

let phone = String(member.phone || '').replace(/\\D/g, '');
if (phone.length === 10) phone = '91' + phone;

const message = `camp17,${name},Your phlebotomist ${phleboName} is on the way for your blood collection.,Contact: ${masked},Track your phlebotomist: ${tracking},Please visit: app.supershyft.com,,Thanks for taking a moment to read this message.`;

return { json: { notification_id: member.notification_id, phone, message } };"""

DELAY_WA = """const member = $input.item.json;
const name = (member.first_name || 'Participant').trim();
const pd = member.participant_details || {};
const phleboName = (pd.phlebo_name || 'Phlebotomist').trim();
const masked = (pd.masked_number || '').trim();
const eta = pd.eta_in_minutes;

let phone = String(member.phone || '').replace(/\\D/g, '');
if (phone.length === 10) phone = '91' + phone;

const message = `camp17,${name},Your phlebotomist ${phleboName} is delayed and will arrive in about ${eta} minutes.,Contact: ${masked},Please visit: app.supershyft.com,,Thanks for taking a moment to read this message.`;

return { json: { notification_id: member.notification_id, phone, message } };"""

ASSIGNED_EMAIL = """const member = $input.item.json;
const name = (member.first_name || 'Participant').trim();
const pd = member.participant_details || {};
const sd = member.session_details || {};
const phleboName = (pd.phlebo_name || 'Phlebotomist').trim();
const collectionDate = (sd.date || '').trim();
const collectionTime = (sd.slot || '').trim();
const masked = (pd.masked_number || '').trim();
const tracking = (pd.tracking_url || '').trim();
const maskedLine = masked ? `\\nContact: ${masked}` : '';
const trackingLine = tracking ? `\\nTrack: ${tracking}` : '';
const body = `Hello ${name},\\n\\nYour phlebotomist ${phleboName} has been assigned for your blood collection.\\n\\nDate: ${collectionDate}\\nTime: ${collectionTime}${maskedLine}${trackingLine}\\n\\nYou can check your details anytime at: app.supershyft.com\\n\\nWarm regards,\\nTeam Supershyft`;
return { json: { notification_id: member.notification_id, to: member.email, subject: 'Your phlebotomist has been assigned', body } };"""

REASSIGNED_EMAIL = ASSIGNED_EMAIL.replace("has been assigned", "has been reassigned").replace(
    "'Your phlebotomist has been assigned'", "'Your phlebotomist has been reassigned'"
)

ENROUTE_EMAIL = """const member = $input.item.json;
const name = (member.first_name || 'Participant').trim();
const pd = member.participant_details || {};
const phleboName = (pd.phlebo_name || 'Phlebotomist').trim();
const masked = (pd.masked_number || '').trim();
const tracking = (pd.tracking_url || '').trim();
const body = `Hello ${name},\\n\\nYour phlebotomist ${phleboName} is on the way for your blood collection.\\n\\nContact: ${masked}\\nTrack: ${tracking}\\n\\nYou can check your details anytime at: app.supershyft.com\\n\\nWarm regards,\\nTeam Supershyft`;
return { json: { notification_id: member.notification_id, to: member.email, subject: 'Your phlebotomist is on the way', body } };"""

DELAY_EMAIL = """const member = $input.item.json;
const name = (member.first_name || 'Participant').trim();
const pd = member.participant_details || {};
const phleboName = (pd.phlebo_name || 'Phlebotomist').trim();
const masked = (pd.masked_number || '').trim();
const eta = pd.eta_in_minutes;
const body = `Hello ${name},\\n\\nYour phlebotomist ${phleboName} is delayed and will arrive in about ${eta} minutes.\\n\\nContact: ${masked}\\n\\nYou can check your details anytime at: app.supershyft.com\\n\\nWarm regards,\\nTeam Supershyft`;
return { json: { notification_id: member.notification_id, to: member.email, subject: 'Your phlebotomist is delayed', body } };"""

CONFIGS = [
    ("phlebo-assigned-whatsapp", "Phlebo Assigned WhatsApp", "pa-wa", "phlebo-assigned-whatsapp-v1", "pa-wh-assigned-wa", True, ASSIGNED_WA, "wa"),
    ("phlebo-assigned-email", "Phlebo Assigned Email", "pa-em", "phlebo-assigned-email-v1", "pa-wh-assigned-em", True, ASSIGNED_EMAIL, "em"),
    ("phlebo-reassigned-whatsapp", "Phlebo Reassigned WhatsApp", "pr-wa", "phlebo-reassigned-whatsapp-v1", "pr-wh-reassigned-wa", True, REASSIGNED_WA, "wa"),
    ("phlebo-reassigned-email", "Phlebo Reassigned Email", "pr-em", "phlebo-reassigned-email-v1", "pr-wh-reassigned-em", True, REASSIGNED_EMAIL, "em"),
    ("phlebo-enroute-whatsapp", "Phlebo Enroute WhatsApp", "pe-wa", "phlebo-enroute-whatsapp-v1", "pe-wh-enroute-wa", False, ENROUTE_WA, "wa"),
    ("phlebo-enroute-email", "Phlebo Enroute Email", "pe-em", "phlebo-enroute-email-v1", "pe-wh-enroute-em", False, ENROUTE_EMAIL, "em"),
    ("phlebo-delay-whatsapp", "Phlebo Delay WhatsApp", "pd-wa", "phlebo-delay-whatsapp-v1", "pd-wh-delay-wa", False, DELAY_WA, "wa"),
    ("phlebo-delay-email", "Phlebo Delay Email", "pd-em", "phlebo-delay-email-v1", "pd-wh-delay-em", False, DELAY_EMAIL, "em"),
]


def main() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    for fname, title, prefix, path, whid, req_sess, prepare_js, kind in CONFIGS:
        sticky = (
            f"## {title}\\nHealthians phlebo webhook participant notification. "
            "Requires participant_details; session_details when assigned/reassigned."
        )
        validate = (
            "Payload validation failed: participant_details and session_details (date, slot) are required"
            if req_sess
            else "Payload validation failed: notification_id, members, and participant_details are required"
        )
        if kind == "wa":
            wf = wa_workflow(
                prefix=prefix,
                title=title,
                path=path,
                webhook_id=whid,
                sticky=sticky,
                require_session=req_sess,
                prepare_js=prepare_js,
                validate_msg=validate,
            )
        else:
            wf = email_workflow(
                prefix=prefix,
                title=title,
                path=path,
                webhook_id=whid,
                sticky=sticky,
                require_session=req_sess,
                prepare_js=prepare_js,
                validate_msg=validate,
            )
        out = BASE / f"{fname}.json"
        out.write_text(json.dumps(wf, indent=2), encoding="utf-8")
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
