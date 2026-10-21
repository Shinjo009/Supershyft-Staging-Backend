"""Helpers to apply platform B2C onboarding defaults when creating engagements."""

from __future__ import annotations

from modules.engagements.enums import ConsultationMode, EngagementPaymentType
from modules.engagements.schemas import _consultations_enabled
from modules.platform_settings.schemas import B2cOnboardingTypeDefaults


def _normalize_gender(gender: str | None) -> str:
    return (gender or "").strip().lower()


def resolve_b2c_diagnostic_package_id(
    defaults: B2cOnboardingTypeDefaults,
    *,
    override_id: int | None,
    gender: str | None,
) -> int | None:
    if override_id is not None:
        return override_id
    g = _normalize_gender(gender)
    if g in {"male", "m"} and defaults.diagnostic_package_id_male:
        return defaults.diagnostic_package_id_male
    if g in {"female", "f"} and defaults.diagnostic_package_id_female:
        return defaults.diagnostic_package_id_female
    return defaults.diagnostic_package_id


def b2c_engagement_create_kwargs_from_defaults(
    defaults: B2cOnboardingTypeDefaults,
    consultations: dict | None,
) -> dict:
    """Keyword args for EngagementsService.create_b2c_engagement beyond packages/profile flags."""
    load_prev = bool(defaults.load_prev_assessment_questionnaires)
    consultation_mode: ConsultationMode | None = None
    if _consultations_enabled(consultations):
        consultation_mode = defaults.consultation_mode or ConsultationMode.online
    return {
        "load_prev_assessment_questionnaires": load_prev,
        "load_prev_questionnaire_category_keys": (
            defaults.load_prev_questionnaire_category_keys if load_prev else None
        ),
        "slot_duration": int(defaults.slot_duration or 20),
        "consultation_mode": consultation_mode,
        "payment_type": defaults.payment_type or EngagementPaymentType.paid_by_patient,
        "auto_booking": bool(defaults.auto_booking),
    }
