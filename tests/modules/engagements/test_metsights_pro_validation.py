from __future__ import annotations

import pytest
from sqlalchemy import text

from core.exceptions import AppError
from modules.engagements.metsights_pro_validation import (
    coerce_b2c_assessment_away_from_pro_when_ineligible,
    missing_metsights_pro_hormone_labels,
    ensure_metsights_pro_allowed_for_engagement,
    ensure_metsights_pro_allowed_before_b2c_draft_pay,
    ensure_metsights_pro_allowed_for_b2c_type_defaults,
    resolve_diagnostic_package_id_for_pro_gate,
)


def test_missing_metsights_pro_hormone_labels_all_present():
    keys = {"lh", "fsh", "total_testosterone", "glucose_fasting"}
    assert missing_metsights_pro_hormone_labels(keys) == []


def test_missing_metsights_pro_hormone_labels_aliases():
    keys = {"lh_value", "fsh_value", "testosterone"}
    assert missing_metsights_pro_hormone_labels(keys) == []


def test_missing_metsights_pro_hormone_labels_partial():
    keys = {"lh", "fsh"}
    assert missing_metsights_pro_hormone_labels(keys) == ["total testosterone"]


def test_resolve_diagnostic_package_id_for_pro_gate_prefers_female():
    assert (
        resolve_diagnostic_package_id_for_pro_gate(
            diagnostic_package_id=10,
            diagnostic_package_id_female=20,
        )
        == 20
    )


@pytest.mark.asyncio
async def test_ensure_metsights_pro_rejects_missing_hormones(test_db_session):
    bio_ai_type_id = (
        await test_db_session.execute(
            text("SELECT id FROM engagement_types WHERE code = 'bio_ai' LIMIT 1")
        )
    ).scalar_one()
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, status) "
            "VALUES (902, 'METSIGHTS_PRO', 'Metsights Pro', 1) ON CONFLICT (package_id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, reference_id, package_name, "
            "diagnostic_provider, status, bookings_count) "
            "VALUES (903, 'REF903', 'No hormones', 'healthians', 1, 0) "
            "ON CONFLICT (diagnostic_package_id) DO NOTHING"
        )
    )
    await test_db_session.commit()

    with pytest.raises(AppError) as exc:
        await ensure_metsights_pro_allowed_for_engagement(
            test_db_session,
            engagement_type_id=int(bio_ai_type_id),
            assessment_package_id=902,
            diagnostic_package_id=903,
            diagnostic_package_id_male=None,
            diagnostic_package_id_female=None,
        )
    assert exc.value.status_code == 400
    assert "missing" in exc.value.message.lower()


@pytest.mark.asyncio
async def test_ensure_metsights_pro_allows_basic_without_hormones(test_db_session):
    bio_ai_type_id = (
        await test_db_session.execute(
            text("SELECT id FROM engagement_types WHERE code = 'bio_ai' LIMIT 1")
        )
    ).scalar_one()
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, status) "
            "VALUES (912, 'METSIGHTS_BASIC', 'Metsights Basic', 1) ON CONFLICT (package_id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, reference_id, package_name, "
            "diagnostic_provider, status, bookings_count) "
            "VALUES (913, 'REF913', 'No hormones', 'healthians', 1, 0) "
            "ON CONFLICT (diagnostic_package_id) DO NOTHING"
        )
    )
    await test_db_session.commit()

    await ensure_metsights_pro_allowed_for_engagement(
        test_db_session,
        engagement_type_id=int(bio_ai_type_id),
        assessment_package_id=912,
        diagnostic_package_id=913,
        diagnostic_package_id_male=None,
        diagnostic_package_id_female=None,
    )


@pytest.mark.asyncio
async def test_coerce_b2c_assessment_falls_back_to_essentials_when_pro_ineligible(test_db_session):
    bio_ai_type_id = (
        await test_db_session.execute(
            text("SELECT id FROM engagement_types WHERE code = 'bio_ai_with_consultation' LIMIT 1")
        )
    ).scalar_one_or_none()
    if bio_ai_type_id is None:
        bio_ai_type_id = (
            await test_db_session.execute(
                text("SELECT id FROM engagement_types WHERE code = 'bio_ai' LIMIT 1")
            )
        ).scalar_one()
    pro_id = (
        await test_db_session.execute(
            text(
                "SELECT package_id FROM assessment_packages "
                "WHERE package_code = 'METSIGHTS_PRO' ORDER BY package_id LIMIT 1"
            )
        )
    ).scalar_one()
    essentials_id = (
        await test_db_session.execute(
            text(
                "SELECT package_id FROM assessment_packages "
                "WHERE package_code = 'METSIGHTS_BASIC' ORDER BY package_id LIMIT 1"
            )
        )
    ).scalar_one()
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, reference_id, package_name, "
            "diagnostic_provider, status, bookings_count) "
            "VALUES (934, 'REF934', 'Supershyft Core+', 'healthians', 1, 0) "
            "ON CONFLICT (diagnostic_package_id) DO NOTHING"
        )
    )
    await test_db_session.commit()

    coerced = await coerce_b2c_assessment_away_from_pro_when_ineligible(
        test_db_session,
        engagement_type_id=int(bio_ai_type_id),
        assessment_package_id=int(pro_id),
        diagnostic_package_id=934,
        diagnostic_package_id_male=None,
        diagnostic_package_id_female=None,
    )
    assert coerced == int(essentials_id)
    assert coerced != int(pro_id)


@pytest.mark.asyncio
async def test_ensure_metsights_pro_b2c_defaults_rejects_pro_without_hormones(test_db_session):
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, status) "
            "VALUES (922, 'METSIGHTS_PRO', 'Metsights Pro', 1) ON CONFLICT (package_id) DO NOTHING"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, reference_id, package_name, "
            "diagnostic_provider, status, bookings_count) "
            "VALUES (923, 'REF923', 'No hormones', 'healthians', 1, 0) "
            "ON CONFLICT (diagnostic_package_id) DO NOTHING"
        )
    )
    await test_db_session.commit()

    with pytest.raises(AppError) as exc:
        await ensure_metsights_pro_allowed_for_b2c_type_defaults(
            test_db_session,
            engagement_type_code="bio_ai",
            assessment_package_id=922,
            diagnostic_package_id=923,
            diagnostic_package_id_male=None,
            diagnostic_package_id_female=None,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_draft_pay_gate_resolves_b2c_defaults_without_crashing(test_db_session):
    """Regression: PlatformSettingsService must be constructed with a repository."""
    import json
    from types import SimpleNamespace

    bio_ai_type_id = (
        await test_db_session.execute(
            text("SELECT id FROM engagement_types WHERE code = 'bio_ai' LIMIT 1")
        )
    ).scalar_one()
    await test_db_session.execute(
        text(
            "INSERT INTO assessment_packages (package_id, package_code, display_name, status) "
            "VALUES (942, 'METSIGHTS_BASIC', 'MetSights Essentials', 1) "
            "ON CONFLICT (package_id) DO UPDATE SET package_code = EXCLUDED.package_code, status = EXCLUDED.status"
        )
    )
    await test_db_session.execute(
        text(
            "INSERT INTO diagnostic_package (diagnostic_package_id, reference_id, package_name, "
            "diagnostic_provider, status, bookings_count) "
            "VALUES (943, 'REF943', 'Core no hormones', 'healthians', 1, 0) "
            "ON CONFLICT (diagnostic_package_id) DO NOTHING"
        )
    )
    by_type = {
        "bio_ai": {
            "assessment_package_id": 942,
            "diagnostic_package_id": 943,
            "blood_collection_type": "home_collection",
            "create_profile_on_metsights": True,
            "enroll_for_fitprint_full": False,
            "auto_booking": False,
            "slot_duration": 20,
            "payment_type": "paid_by_patient",
        }
    }
    await test_db_session.execute(text("DELETE FROM platform_settings"))
    await test_db_session.execute(
        text(
            "INSERT INTO platform_settings ("
            "settings_id, b2c_default_assessment_package_id, b2c_default_diagnostic_package_id, "
            "b2c_default_engagement_type, b2c_onboarding_by_engagement_type"
            ") VALUES (1, 942, 943, 'bio_ai', CAST(:by_type AS jsonb))"
        ),
        {"by_type": json.dumps(by_type)},
    )
    await test_db_session.commit()

    engagement = SimpleNamespace(
        enforce_metsights_pro_gate=True,
        engagement_type=int(bio_ai_type_id),
        assessment_package_id=None,
        diagnostic_package_id=943,
        diagnostic_package_id_male=None,
        diagnostic_package_id_female=None,
    )

    await ensure_metsights_pro_allowed_before_b2c_draft_pay(test_db_session, engagement=engagement)
    assert engagement.assessment_package_id == 942
