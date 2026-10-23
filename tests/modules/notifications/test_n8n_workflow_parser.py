"""Tests for n8n workflow → notification content parser."""

from modules.notifications.n8n_workflow_parser import (
    find_chained_dispatches,
    parse_whatsapp_message_from_js,
    parse_workflow,
)


def _minimal_workflow(name: str, js: str) -> dict:
    return {
        "nodes": [
            {
                "name": name,
                "type": "n8n-nodes-base.webhook",
                "parameters": {"path": "welcome-whatsapp-v3"},
            },
            {
                "name": "Prepare WhatsApp Message",
                "type": "n8n-nodes-base.code",
                "parameters": {"jsCode": js},
            },
        ]
    }


def test_parse_welcome_camp13():
    js = (
        "const member = $input.item.json;\n"
        "const name = (member.first_name || 'Participant').trim();\n"
        "const message =\n"
        "`camp13,${name},Thank you so much for trusting us and taking the first step towards prevention.,"
        "Your SuperShyft health profile is ready! ,Please take a few minutes to complete your Health Assessment.,"
        "Your inputs help build your Bio AI Health Report.,Please visit: app.supershyft.com`;\n"
        "return { json: { message } };\n"
    )
    parsed = parse_workflow(_minimal_workflow("Welcome", js))
    assert parsed.primary is not None
    assert parsed.primary.template_name == "camp13"
    assert parsed.primary.template_variables is not None
    assert parsed.primary.template_variables[0] == "{{first_name}}"
    assert "Thank you so much" in str(parsed.primary.template_variables[1])


def test_parse_booking_alert_camp16():
    js = (
        "const agentName = (item.first_name || 'Agent').trim();\n"
        "const pd = item.participant_details || {};\n"
        "const detailsName  = pd.name  || 'New Participant';\n"
        "const bookingDate  = pd.collection_date || 'N/A';\n"
        "const message =\n"
        "  `camp16,${agentName},Please initiate the process and proceed with the booking,` +\n"
        "  `Details Name: ${detailsName} Phone: ${detailsPhone} Email: ${detailsEmail},` +\n"
        "  `Date: ${bookingDate} Time: ${bookingTime} Cabin: ${cabinName},` +\n"
        "  `Address in Admin Please visit:https://admin.supershyft.com/`;\n"
    )
    tn, tv = parse_whatsapp_message_from_js(js)
    assert tn == "camp16"
    assert tv is not None
    assert tv[0] == "{{first_name}}"
    assert any("{{participant_details.name}}" in str(v) for v in tv)


def test_parse_camp17_booking_confirmation():
    js = (
        "const name = 'Test';\n"
        "const collectionDate = '2024-01-01';\n"
        "const collectionTime = '10:00';\n"
        "const cabinName = '';\n"
        "const message = `camp17,${name},Confirmed.,Date: ${collectionDate},"
        "Time: ${collectionTime},Journey.,app.supershyft.com,${cabinName},Thanks.`;\n"
    )
    tn, tv = parse_whatsapp_message_from_js(js)
    assert tn == "camp17"
    assert "{{first_name}}" in tv
    joined = " ".join(str(v) for v in tv)
    assert "{{session_details.date}}" in joined
    assert "{{session_details.slot}}" in joined


def test_chained_dispatch_detection():
    wf = {
        "nodes": [
            {
                "name": "Dispatch Welcome",
                "type": "n8n-nodes-base.httpRequest",
                "parameters": {
                    "url": "https://api.supershyft.com/notifications/dispatch",
                    "jsonBody": '{"service_key":"welcome-booking-whatsapp-1plus1-v1"}',
                },
            }
        ]
    }
    chains = find_chained_dispatches(wf)
    assert len(chains) == 1
    assert chains[0]["service_key"] == "welcome-booking-whatsapp-1plus1-v1"
