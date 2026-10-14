"""Tests for engagement participant progress stage computation."""

from modules.engagements.participant_progress import (
    compute_participant_progress_payload,
    consultation_stage_statuses,
    stage_keys_for_engagement_type,
    _offered_consultation_types,
)
from modules.engagements.participant_progress_e2e import (
    compute_e2e_participant_progress_payload,
    e2e_stage_keys_for_engagement_type,
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
    consult_summary = payload["summary"]["by_stage"]["consultation_booked"]
    assert consult_summary["not_applicable"] == 0
    assert consult_summary["complete"] == 0
    assert consult_summary["pending"] == 1


def test_consult_not_applicable_without_want():
    booked, done, na = consultation_stage_statuses(
        {"doctor": {"want": False}},
        ["doctor"],
    )
    assert na is True
    assert booked is False
    assert done is False

    payload = compute_participant_progress_payload(
        engagement_type_code="bio_ai_with_consultation",
        engagement_consultations={"doctor": True},
        completeness_participants=[
            {
                "user_id": 1,
                "has_booking_id": False,
                "has_blood_report": False,
                "has_blood_values": False,
                "has_bio_ai_report": False,
                "has_bio_ai_json": True,
                "questionnaire_state": "not_started",
            }
        ],
        consultations_by_user={1: {"doctor": {"want": False}}},
    )
    assert payload["summary"]["by_stage"]["consultation_booked"]["not_applicable"] == 1
    assert payload["summary"]["by_stage"]["consultation_booked"]["applicable"] == 0


def test_offered_consultation_object_shape():
    assert _offered_consultation_types({"doctor": {"enabled": True}}) == ["doctor"]


def test_bio_ai_json_requires_blood_values():
    payload = compute_participant_progress_payload(
        engagement_type_code="bio_ai_with_consultation",
        engagement_consultations={},
        completeness_participants=[
            {
                "user_id": 1,
                "has_booking_id": True,
                "has_blood_report": False,
                "has_blood_values": False,
                "has_bio_ai_report": False,
                "has_bio_ai_json": True,
                "questionnaire_state": "filled",
            }
        ],
        consultations_by_user={1: {}},
    )
    assert payload["participants"][0]["stages"]["bio_ai_json"] is False


def test_e2e_notification_sent_counts_complete():
    keys = e2e_stage_keys_for_engagement_type("bio_ai_with_consultation")
    assert "onboarding_notify" in keys
    payload = compute_e2e_participant_progress_payload(
        engagement_type_code="bio_ai_with_consultation",
        engagement={
            "assessment_package_id": 1,
            "diagnostic_package_id": 2,
            "start_date": "2026-01-01",
            "end_date": "2026-01-02",
            "slot_detail": {},
        },
        engagement_consultations={"doctor": True},
        completeness_participants=[
            {
                "user_id": 10,
                "first_name": "A",
                "last_name": "B",
                "has_booking_id": False,
                "has_blood_report": False,
                "has_blood_values": False,
                "has_bio_ai_report": False,
                "has_bio_ai_json": False,
                "questionnaire_state": "not_started",
            }
        ],
        participant_extras_by_user={
            10: {
                "engagement_date": "2026-01-01",
                "slot_start_time": "09:00:00",
                "is_profile_created_on_metsights": False,
            }
        },
        consultations_by_user={10: {"doctor": {"want": False}}},
        event_service_keys={"onboarding": ["onboarding-whatsapp"]},
        onboarding_assistant_count=1,
        dispatch_per_user={(10, "onboarding-whatsapp"): "sent"},
        dispatch_per_engagement={},
    )
    assert payload["participants"][0]["stages"]["onboarding_notify"]["status"] == "complete"
    assert payload["summary"]["by_stage"]["consultation_booked"]["not_applicable"] == 1
