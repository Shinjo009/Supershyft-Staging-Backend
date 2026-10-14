"""Tests for engagement participant progress stage computation."""

from modules.engagements.participant_progress import (
    compute_participant_progress_payload,
    stage_keys_for_engagement_type,
)


def test_stage_keys_bio_ai_with_consultation():
    keys = stage_keys_for_engagement_type("bio_ai_with_consultation")
    assert "bio_ai_report" in keys
    assert "consultation_done" in keys
    assert keys.index("booking_id") < keys.index("consultation_done")


def test_compute_progress_bottleneck():
    payload = compute_participant_progress_payload(
        engagement_type_code="bio_ai_with_consultation",
        engagement_consultations={"doctor": True},
        completeness_participants=[
            {
                "user_id": 1,
                "first_name": "A",
                "last_name": "B",
                "phone": "91",
                "email": "a@b.com",
                "has_booking_id": False,
                "has_blood_report": False,
                "has_blood_values": False,
                "has_bio_ai_report": False,
                "has_bio_ai_json": False,
                "questionnaire_state": "not_started",
            }
        ],
        consultations_by_user={1: {"doctor": {"want": True}}},
    )
    assert payload["summary"]["total_participants"] == 1
    assert payload["participants"][0]["bottleneck"] == "booking_id"
    assert payload["summary"]["stage_counts"]["enrolled"] == 1
