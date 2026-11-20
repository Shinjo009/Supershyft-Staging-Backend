"""Tests for consultation type list formatting in notifications."""

from modules.experts.consultations import (
    consultation_type_enabled,
    format_consultation_types_list,
)


def test_consultation_type_enabled_bool_and_want():
    assert consultation_type_enabled(True)
    assert not consultation_type_enabled(False)
    assert consultation_type_enabled({"want": True})
    assert not consultation_type_enabled({"want": False})


def test_format_one_type():
    assert format_consultation_types_list({"doctor": True}) == "doctor"


def test_format_two_types():
    assert (
        format_consultation_types_list(
            {"doctor": True, "nutrition": True},
            type_keys_order=["doctor", "nutrition", "ayurveda"],
        )
        == "doctor and nutrition"
    )


def test_format_three_types_no_oxford_comma():
    assert (
        format_consultation_types_list(
            {"doctor": True, "nutrition": True, "ayurveda": True},
            type_keys_order=["doctor", "nutrition", "ayurveda"],
        )
        == "doctor, nutrition and ayurveda"
    )


def test_format_omits_disabled():
    assert (
        format_consultation_types_list(
            {"doctor": True, "nutrition": False, "ayurveda": True},
            type_keys_order=["doctor", "nutrition", "ayurveda"],
        )
        == "doctor and ayurveda"
    )


def test_format_empty_map():
    assert format_consultation_types_list({}) == ""
    assert format_consultation_types_list(None) == ""