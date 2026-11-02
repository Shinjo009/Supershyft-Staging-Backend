"""Unit tests for participant home-collection location helpers."""

from modules.engagements.models import Engagement, EngagementParticipant
from modules.engagements.participant_location import booking_location_field


def test_b2c_booking_location_uses_engagement_not_participant_home():
    engagement = Engagement(organization_id=None, address="Engagement Addr", pincode="560001")
    participant = EngagementParticipant(address="Participant Home", pincode="110001")
    assert booking_location_field(participant, engagement, "address") == "Engagement Addr"
    assert booking_location_field(participant, engagement, "pincode") == "560001"


def test_b2b_booking_location_uses_participant_when_home_set():
    engagement = Engagement(organization_id=99, address="Office Camp", pincode="560100")
    participant = EngagementParticipant(address="Home 42", pincode="560001")
    assert booking_location_field(participant, engagement, "address") == "Home 42"
    assert booking_location_field(participant, engagement, "pincode") == "560001"


def test_b2b_booking_location_falls_back_to_engagement_without_participant_home():
    engagement = Engagement(organization_id=99, address="Office Camp", pincode="560100")
    participant = EngagementParticipant()
    assert booking_location_field(participant, engagement, "address") == "Office Camp"
    assert booking_location_field(participant, engagement, "pincode") == "560100"
