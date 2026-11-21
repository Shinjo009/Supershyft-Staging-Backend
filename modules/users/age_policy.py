"""Shared 18+ policy: validate age/DOB from API payloads and derive stored DOB + provenance.

Age-only input uses January 1 of (business_year - age) as an explicit approximation,
not the person's real birthday. Self-reported age is not verified.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from modules.dashboard.command_period import command_today

MINIMUM_ACCOUNT_AGE = 18
MAXIMUM_ACCOUNT_AGE = 120

DobProvenance = Literal[
    "genuine",
    "estimated_from_age",
    "migration_estimated",
    "unknown",
]

MINIMUM_AGE_MESSAGE = "You must be at least 18 years old to create an account."


@dataclass(frozen=True)
class AgePolicyResult:
    date_of_birth: date
    provenance: DobProvenance
    computed_age: int
    reference_year: int | None = None


class AgePolicyValidationError(Exception):
    """Local validation failure; map to AppError in service layer."""

    def __init__(self, message: str, *, error_code: str = "INVALID_INPUT") -> None:
        self.message = message
        self.error_code = error_code
        super().__init__(message)


def business_date_today(*, today: date | None = None) -> date:
    return command_today(today=today)


def parse_age_from_payload(value: Any) -> int:
    """Strict integer age parsing (reject bool, float, empty)."""
    if value is None or value == "":
        raise AgePolicyValidationError("age is required")
    if isinstance(value, bool):
        raise AgePolicyValidationError("age must be a whole number")
    if isinstance(value, float):
        if not value.is_integer():
            raise AgePolicyValidationError("age must be a whole number")
        value = int(value)
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise AgePolicyValidationError("age must be a whole number")
        value = int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise AgePolicyValidationError("age is required")
        try:
            if "." in stripped:
                raise AgePolicyValidationError("age must be a whole number")
            value = int(stripped, 10)
        except ValueError as exc:
            raise AgePolicyValidationError("age must be a whole number") from exc
    if not isinstance(value, int):
        raise AgePolicyValidationError("age must be a whole number")
    if value < MINIMUM_ACCOUNT_AGE or value > MAXIMUM_ACCOUNT_AGE:
        if value < MINIMUM_ACCOUNT_AGE:
            raise AgePolicyValidationError(MINIMUM_AGE_MESSAGE, error_code="MINIMUM_AGE_REQUIRED")
        raise AgePolicyValidationError(f"age must be between {MINIMUM_ACCOUNT_AGE} and {MAXIMUM_ACCOUNT_AGE}")
    return value


def completed_calendar_years(*, date_of_birth: date, reference_date: date) -> int:
    """Completed years at reference_date; eligibility starts on the birthday (inclusive)."""
    years = reference_date.year - date_of_birth.year
    had_birthday = (reference_date.month, reference_date.day) >= (
        date_of_birth.month,
        date_of_birth.day,
    )
    return years if had_birthday else years - 1


def compute_age_from_dob(*, date_of_birth: date | None, reference_date: date) -> int | None:
    if date_of_birth is None:
        return None
    return completed_calendar_years(date_of_birth=date_of_birth, reference_date=reference_date)


def estimate_dob_from_age(*, age: int, business_date: date) -> date:
    year = business_date.year - int(age)
    return date(max(year, 1900), 1, 1)


def resolve_single_dob(
    *,
    dob: date | None = None,
    date_of_birth: date | None = None,
) -> date | None:
    """Resolve dob/date_of_birth aliases; reject conflicting values."""
    if dob is not None and date_of_birth is not None and dob != date_of_birth:
        raise AgePolicyValidationError("dob and date_of_birth must match when both are provided")
    return dob if dob is not None else date_of_birth


def validate_future_dob(dob: date, *, business_date: date) -> None:
    if dob > business_date:
        raise AgePolicyValidationError("date of birth cannot be in the future")


def resolve_new_user_age_and_dob(
    *,
    age: Any | None = None,
    dob: date | None = None,
    date_of_birth: date | None = None,
    business_date: date | None = None,
    reference_year_for_estimate: int | None = None,
) -> AgePolicyResult:
    """Apply precedence: genuine DOB wins; else validated age >= 18 with Jan-1 estimate."""
    ref = business_date or business_date_today()
    genuine = resolve_single_dob(dob=dob, date_of_birth=date_of_birth)

    if genuine is not None:
        validate_future_dob(genuine, business_date=ref)
        years = completed_calendar_years(date_of_birth=genuine, reference_date=ref)
        if years < MINIMUM_ACCOUNT_AGE:
            raise AgePolicyValidationError(MINIMUM_AGE_MESSAGE, error_code="MINIMUM_AGE_REQUIRED")
        return AgePolicyResult(
            date_of_birth=genuine,
            provenance="genuine",
            computed_age=years,
            reference_year=None,
        )

    parsed_age = parse_age_from_payload(age)
    est_year = reference_year_for_estimate if reference_year_for_estimate is not None else ref.year
    estimated = date(max(est_year - parsed_age, 1900), 1, 1)
    return AgePolicyResult(
        date_of_birth=estimated,
        provenance="estimated_from_age",
        computed_age=parsed_age,
        reference_year=est_year,
    )


def migration_estimate_dob(
    *,
    stored_age: int,
    created_at_year: int | None,
    fallback_business_year: int,
) -> AgePolicyResult:
    """Legacy backfill: Jan 1 of (reference year - stored age). No 18+ filter."""
    if stored_age < 1 or stored_age > MAXIMUM_ACCOUNT_AGE:
        raise AgePolicyValidationError("invalid stored age for migration")
    ref_year = created_at_year if created_at_year is not None else fallback_business_year
    estimated = date(max(ref_year - stored_age, 1900), 1, 1)
    return AgePolicyResult(
        date_of_birth=estimated,
        provenance="migration_estimated",
        computed_age=stored_age,
        reference_year=ref_year,
    )


def user_computed_age(user, *, business_date: date | None = None) -> int | None:
    """Display/API age from persisted DOB when present, else cached column."""
    ref = business_date or business_date_today()
    if user.date_of_birth is not None:
        return compute_age_from_dob(date_of_birth=user.date_of_birth, reference_date=ref)
    return user.age


def policy_result_as_user_attrs(result: AgePolicyResult) -> dict[str, Any]:
    return {
        "age": result.computed_age,
        "date_of_birth": result.date_of_birth,
        "dob_provenance": result.provenance,
        "dob_estimate_reference_year": result.reference_year,
    }