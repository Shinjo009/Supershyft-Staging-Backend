"""Unit tests for family onboard request schemas."""

import pytest
from pydantic import ValidationError

from modules.users.schemas import FamilyOnboardStartRequest, FamilyOnboardVerifyPayRequest


def test_family_onboard_requires_unique_member_phones():
    payload = {
        "booker": {"name": "Adi", "phone": "9000000001", "email": "a@example.com"},
        "members": [
            {
                "name": "M1",
                "phone": "9000000002",
                "relation": "child",
                "age": 10,
                "blood_collection_date": "2026-01-01",
                "blood_collection_time_slot": "09:00",
            },
            {
                "name": "M2",
                "phone": "9000000002",
                "relation": "spouse",
                "age": 30,
                "blood_collection_date": "2026-01-01",
                "blood_collection_time_slot": "10:00",
            },
        ],
    }
    with pytest.raises(ValidationError):
        FamilyOnboardStartRequest.model_validate(payload)


def test_family_onboard_requires_blood_fields_for_bio_ai():
    payload = {
        "booker": {"name": "Adi", "phone": "9000000001", "email": "a@example.com"},
        "members": [
            {
                "name": "M1",
                "phone": "9000000002",
                "relation": "child",
                "age": 10,
            },
        ],
    }
    with pytest.raises(ValidationError):
        FamilyOnboardStartRequest.model_validate(payload)


def test_family_onboard_accepts_valid_payload():
    payload = {
        "booker": {"name": "Adi Kumar", "phone": "9000000001", "email": "a@example.com"},
        "members": [
            {
                "name": "M1",
                "phone": "9000000002",
                "relation": "child",
                "age": 10,
                "blood_collection_date": "2026-01-01",
                "blood_collection_time_slot": "09:00",
            },
        ],
    }
    model = FamilyOnboardStartRequest.model_validate(payload)
    assert model.members[0].engagement_type == "bio_ai"


def test_family_onboard_verify_pay_requires_engagement_ids():
    with pytest.raises(ValidationError):
        FamilyOnboardVerifyPayRequest.model_validate(
            {"phone": "9000000001", "otp": "1234", "engagement_ids": []}
        )


def test_family_onboard_verify_pay_rejects_duplicate_engagement_ids():
    with pytest.raises(ValidationError):
        FamilyOnboardVerifyPayRequest.model_validate(
            {
                "phone": "9000000001",
                "otp": "1234",
                "engagement_ids": [1, 1],
            }
        )


def test_family_onboard_verify_pay_accepts_valid_payload():
    model = FamilyOnboardVerifyPayRequest.model_validate(
        {
            "phone": "9000000001",
            "otp": "1234",
            "engagement_ids": [10, 20],
            "discount_code": "SAVE10",
        }
    )
    assert model.engagement_ids == [10, 20]
