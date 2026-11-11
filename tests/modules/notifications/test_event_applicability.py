"""Engagement notification applicability rules."""

from modules.notifications.event_applicability import (
    engagement_notification_applicable,
    profile_from_mapping,
    show_on_engagement_wizard,
)


def test_camp_pretest_applicable():
    profile = profile_from_mapping(
        {
            "engagement_kind": "blood_test",
            "blood_collection_type": "camp_collection",
            "auto_booking": False,
        }
    )
    assert engagement_notification_applicable("reminders.pretest", profile)


def test_pretest_on_home_collection_for_blood_types():
    profile = profile_from_mapping(
        {
            "engagement_kind": "blood_test",
            "blood_collection_type": "home_collection",
            "auto_booking": True,
        }
    )
    assert engagement_notification_applicable("reminders.pretest", profile)
    assert engagement_notification_applicable("bookings.phlebo_assigned", profile)


def test_questionnaire_reminders_bio_ai_only():
    bio_ai_home = profile_from_mapping(
        {
            "engagement_kind": "bio_ai",
            "blood_collection_type": "home_collection",
            "auto_booking": True,
        }
    )
    blood_only = profile_from_mapping(
        {
            "engagement_kind": "blood_test",
            "blood_collection_type": "camp_collection",
            "auto_booking": False,
        }
    )
    assert engagement_notification_applicable("reminders.questionnaire_before", bio_ai_home)
    assert engagement_notification_applicable("reminders.questionnaire_after", bio_ai_home)
    assert not engagement_notification_applicable("reminders.questionnaire_before", blood_only)
    assert not engagement_notification_applicable("reminders.questionnaire_after", blood_only)


def test_payments_completed_for_paid_by_patient_engagements():
    profile = profile_from_mapping(
        {
            "engagement_kind": "bio_ai_with_consultation",
            "blood_collection_type": "home_collection",
            "auto_booking": False,
            "consultation_mode": "online",
            "payment_type": "paid_by_patient",
        }
    )
    assert engagement_notification_applicable("payments.completed", profile)
    assert show_on_engagement_wizard("payments.completed")


def test_payments_completed_not_on_paid_by_group_camp():
    profile = profile_from_mapping(
        {
            "engagement_kind": "blood_test",
            "blood_collection_type": "camp_collection",
            "payment_type": "paid_by_group",
        }
    )
    assert not engagement_notification_applicable("payments.completed", profile)
