"""One-off builder: family-onboard WhatsApp n8n JSON from booking-confirmation template."""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "n8n" / "workflows" / "booking-confirmation-whatsapp.json"
OUT_DIR = ROOT / "n8n" / "workflows"
META = {
    "instanceId": "eed8b3457b986f6362867dfc9a5378439da2846ec92ad64fddac97c84b5cba32"
}

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

SENDER_PREPARE = """const member = $input.item.json;
const pd = member.participant_details || {};
const bookerName = (pd.booker_name || member.first_name || 'there').trim();
const recipientName = (pd.recipient_name || '-').trim();
const relationship = (pd.relationship || '-').trim();
const giftUrl = (pd.gift_url || 'https://app.supershyft.com').trim();

let phone = String(member.phone || '').replace(/\\D/g, '');
if (phone.length === 10) phone = '91' + phone;

const message = `camp17,${bookerName},Hello ${bookerName},This Diwali you are giving someone you love something truly special through the gift of health and well being.,Your personalised BIO AI Wellness Assessment for ${recipientName} is being created with love.,Recipient Name: ${recipientName},Relationship: ${relationship},Because the people we love deserve a healthier and happier life with many more beautiful moments together.,You can check the details below for your convenience.,${giftUrl},Thank you for choosing to make someone's well being a little more special this Diwali`;

return {
  json: {
    notification_id: member.notification_id,
    phone,
    message
  }
};"""

RECEIVER_PREPARE = """const member = $input.item.json;
const pd = member.participant_details || {};
const recipientName = (pd.recipient_name || member.first_name || 'there').trim();
const bookerName = (pd.booker_name || '-').trim();
const giftUrl = (pd.gift_url || 'https://app.supershyft.com').trim();

let phone = String(member.phone || '').replace(/\\D/g, '');
if (phone.length === 10) phone = '91' + phone;

const message = `camp17,${recipientName},Hello ${recipientName},Guess what. Someone who loves you has a special surprise for you this Diwali.,${bookerName} has gifted you a personalised BIO AI Wellness Assessment because your health and happiness mean so much to them.,It is their little way of saying that your health matters to me and I want you around for many many more celebrations.,Your gift will help you understand your health better through personalised BIO AI insights and recommendations to support your well being and healthy lifestyle.,You can explore your special gift here.,${giftUrl},May this Diwali bring you good health peaceful moments endless laughter and countless beautiful memories with the people who love you.,Happy Diwali and lots of love to you`;

return {
  json: {
    notification_id: member.notification_id,
    phone,
    message
  }
};"""


def _pd_field_cond(cid: str, field: str) -> dict:
    return {
        "id": cid,
        "leftValue": f"={{{{ $json.body.participant_details.{field} }}}}",
        "rightValue": "",
        "operator": {"type": "string", "operation": "exists", "singleValue": True},
    }


def _build_conditions(sender: bool) -> list[dict]:
    conds = [
        {
            "id": "fog-notif",
            "leftValue": "={{ $json.body.notification_id }}",
            "rightValue": 0,
            "operator": {"type": "number", "operation": "exists", "singleValue": True},
        },
        {
            "id": "fog-members",
            "leftValue": "={{ $json.body.members }}",
            "rightValue": "",
            "operator": {"type": "array", "operation": "exists", "singleValue": True},
        },
        {
            "id": "fog-len",
            "leftValue": "={{ $json.body.members.length }}",
            "rightValue": 0,
            "operator": {"type": "number", "operation": "gt"},
        },
        {
            "id": "fog-pd",
            "leftValue": "={{ $json.body.participant_details }}",
            "rightValue": "",
            "operator": {"type": "object", "operation": "exists", "singleValue": True},
        },
        _pd_field_cond("fog-booker", "booker_name"),
        _pd_field_cond("fog-recipient", "recipient_name"),
        _pd_field_cond("fog-gift", "gift_url"),
    ]
    if sender:
        conds.append(_pd_field_cond("fog-rel", "relationship"))
    return conds


CONFIGS = [
    {
        "file": "family-onboard-sender-whatsapp.json",
        "path": "family-onboard-sender-whatsapp-v1",
        "webhook_name": "Family Onboard Sender WhatsApp",
        "webhook_id": "fos-wh-sender-v1",
        "prepare_name": "Prepare Family Onboard Sender WhatsApp",
        "sticky": (
            "## Family Onboard Gift Sender WhatsApp (camp17)\n\n"
            "Required payload:\n"
            "{\n"
            "  notification_id: number,\n"
            "  members: [{ first_name, last_name, email, phone }],\n"
            "  participant_details: { booker_name, recipient_name, relationship, gift_url },\n"
            "  engagement_id?: number\n"
            "}\n\n"
            "camp17 multi-segment CSV (same shape as thank-you-feedback / booking-confirmation): "
            "bookerName, Hello bookerName, …, recipientName, relationship, giftUrl, closing line."
        ),
        "validate_msg": (
            "Payload validation failed: notification_id, members, and participant_details "
            "(booker_name, recipient_name, relationship, gift_url) are required"
        ),
        "sender": True,
        "prepare_js": SENDER_PREPARE,
    },
    {
        "file": "family-onboard-receiver-whatsapp.json",
        "path": "family-onboard-receiver-whatsapp-v1",
        "webhook_name": "Family Onboard Receiver WhatsApp",
        "webhook_id": "fos-wh-receiver-v1",
        "prepare_name": "Prepare Family Onboard Receiver WhatsApp",
        "sticky": (
            "## Family Onboard Gift Receiver WhatsApp (camp17)\n\n"
            "Required payload:\n"
            "{\n"
            "  notification_id: number,\n"
            "  members: [{ first_name, last_name, email, phone }],\n"
            "  participant_details: { booker_name, recipient_name, gift_url },\n"
            "  engagement_id?: number\n"
            "}\n\n"
            "camp17 multi-segment CSV: recipientName, Hello recipientName, …, bookerName, giftUrl, Diwali closing."
        ),
        "validate_msg": (
            "Payload validation failed: notification_id, members, and participant_details "
            "(booker_name, recipient_name, gift_url) are required"
        ),
        "sender": False,
        "prepare_js": RECEIVER_PREPARE,
    },
]


def build_workflow(cfg: dict) -> dict:
    template = json.loads(BASE.read_text(encoding="utf-8"))
    wf = copy.deepcopy(template)
    wf["meta"] = META
    prepare_name = cfg["prepare_name"]
    webhook_name = cfg["webhook_name"]

    for node in wf["nodes"]:
        node_type = node.get("type")
        name = node.get("name")
        if node_type == "n8n-nodes-base.stickyNote":
            node["parameters"]["content"] = cfg["sticky"]
            node["name"] = f"Sticky Note {webhook_name}"
        elif node_type == "n8n-nodes-base.webhook":
            node["parameters"]["path"] = cfg["path"]
            node["name"] = webhook_name
            node["webhookId"] = cfg["webhook_id"]
        elif name == "Validate WhatsApp Payload":
            node["parameters"]["conditions"]["conditions"] = _build_conditions(cfg["sender"])
        elif name == "Split Members":
            node["parameters"]["jsCode"] = SPLIT_JS
        elif name == "Prepare Booking Confirmation WhatsApp":
            node["name"] = prepare_name
            node["parameters"]["jsCode"] = cfg["prepare_js"]
        elif name == "WhatsApp Validation Failed":
            for assignment in node["parameters"]["assignments"]["assignments"]:
                if assignment["name"] == "notification_id":
                    assignment["value"] = (
                        f"={{{{ $('{webhook_name}').item.json.body.notification_id }}}}"
                    )
                if assignment["name"] == "message":
                    assignment["value"] = cfg["validate_msg"]
        elif name in (
            "WhatsApp Sent Response",
            "WhatsApp Failed Response",
            "WhatAPI Not Accepted",
        ):
            for assignment in node["parameters"]["assignments"]["assignments"]:
                if assignment["name"] == "notification_id":
                    assignment["value"] = (
                        f"={{{{ $('{prepare_name}').item.json.notification_id }}}}"
                    )

    con = wf["connections"]
    con[webhook_name] = con.pop("Booking Confirmation WhatsApp")
    con[prepare_name] = con.pop("Prepare Booking Confirmation WhatsApp")
    return wf


def main() -> None:
    for cfg in CONFIGS:
        path = OUT_DIR / cfg["file"]
        path.write_text(json.dumps(build_workflow(cfg), indent=2), encoding="utf-8")
        print("wrote", path.name)


if __name__ == "__main__":
    main()
