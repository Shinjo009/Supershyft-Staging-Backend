"""Tests for shared gender normalization."""

from db.column_types import UserGender
from modules.users.gender_labels import normalize_gender_label


def test_normalize_user_gender_enum_members():
    assert normalize_gender_label(UserGender.male) == "male"
    assert normalize_gender_label(UserGender.male_capitalized) == "male"
    assert normalize_gender_label(UserGender.female) == "female"
    assert normalize_gender_label(UserGender.female_capitalized) == "female"


def test_normalize_user_gender_enum_string_leaks():
    assert normalize_gender_label("usergender.male_capitalized") == "male"
    assert normalize_gender_label("UserGender.female_capitalized") == "female"
    assert normalize_gender_label("male_capitalized") == "male"


def test_normalize_user_gender_common_labels():
    assert normalize_gender_label("Male") == "male"
    assert normalize_gender_label("F") == "female"
    assert normalize_gender_label(1) == "male"
    assert normalize_gender_label("2") == "female"
    assert normalize_gender_label("other") is None
