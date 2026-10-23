"""DispatchRequest validation (admin send-message)."""

from modules.notifications.schemas import DispatchRequest


def test_dispatch_request_strips_blank_participant_detail_fields():
    req = DispatchRequest(
        service_key="welcome-whatsapp",
        user_ids=[1],
        participant_details={
            "name": "Pooja Nair",
            "email": "",
            "phone": "918762830757",
            "engagement": "",
        },
    )
    assert req.participant_details == {"name": "Pooja Nair", "phone": "918762830757"}
