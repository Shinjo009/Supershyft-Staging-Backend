"""Unit tests for shared age/DOB policy."""

from __future__ import annotations

from datetime import date

import pytest

from modules.users.age_policy import (
    AgePolicyValidationError,
    completed_calendar_years,
    estimate_dob_from_age,
    migration_estimate_dob,
    parse_age_from_payload,
    resolve_new_user_age_and_dob,
)


def test_age_18_january_first_estimated():
    ref = date(2026, 11, 21)
    result = resolve_new_user_age_and_dob(age=18, business_date=ref)
    assert result.date_of_birth == date(2008, 1, 1)
    assert result.provenance == "estimated_from_age"
    assert result.computed_age == 18


def test_age_17_rejected():
    with pytest.raises(AgePolicyValidationError) as exc:
        resolve_new_user_age_and_dob(age=17, business_date=date(2026, 11, 21))
    assert exc.value.error_code == "MINIMUM_AGE_REQUIRED"


def test_genuine_underage_dob_rejects_even_with_adult_age():
    with pytest.raises(AgePolicyValidationError) as exc:
        resolve_new_user_age_and_dob(
            age=18,
            dob=date(2008, 12, 1),
            business_date=date(2026, 11, 21),
        )
    assert exc.value.error_code == "MINIMUM_AGE_REQUIRED"


def test_genuine_adult_dob_governs():
    result = resolve_new_user_age_and_dob(
        age=99,
        dob=date(1990, 6, 15),
        business_date=date(2026, 11, 21),
    )
    assert result.provenance == "genuine"
    assert result.computed_age == 36


def test_invalid_dob_does_not_fall_back_to_age():
    with pytest.raises(AgePolicyValidationError):
        resolve_new_user_age_and_dob(
            age=25,
            dob=date(2030, 1, 1),
            business_date=date(2026, 11, 21),
        )


def test_january_first_genuine_not_treated_as_estimate_by_provenance():
    result = resolve_new_user_age_and_dob(
        age=40,
        dob=date(1986, 1, 1),
        business_date=date(2026, 11, 21),
    )
    assert result.provenance == "genuine"


def test_parse_age_rejects_bool_and_float():
    with pytest.raises(AgePolicyValidationError):
        parse_age_from_payload(True)
    with pytest.raises(AgePolicyValidationError):
        parse_age_from_payload(18.5)


def test_leap_day_completed_years():
    dob = date(2008, 2, 29)
    assert completed_calendar_years(date_of_birth=dob, reference_date=date(2026, 2, 28)) == 17
    assert completed_calendar_years(date_of_birth=dob, reference_date=date(2026, 3, 1)) == 18


def test_migration_uses_created_at_year():
    result = migration_estimate_dob(
        stored_age=30,
        created_at_year=2020,
        fallback_business_year=2026,
    )
    assert result.date_of_birth == date(1990, 1, 1)
    assert result.provenance == "migration_estimated"
    assert result.reference_year == 2020


def test_estimate_dob_from_age_matches_convention():
    assert estimate_dob_from_age(age=18, business_date=date(2026, 7, 4)) == date(2008, 1, 1)