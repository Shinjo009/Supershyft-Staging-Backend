"""MetSights Essentials optional vitals helpers."""

from modules.assessments.essentials_vitals import (
    category_optional_for_essentials_completion,
    filter_incomplete_for_essentials_completion,
    is_metsights_essentials,
    is_only_optional_vitals_gap,
)


def test_is_metsights_essentials_by_type_and_code():
    assert is_metsights_essentials(type_code="1")
    assert is_metsights_essentials(package_code="METSIGHTS_BASIC")
    assert not is_metsights_essentials(type_code="2")
    assert not is_metsights_essentials(package_code="METSIGHTS_PRO")


def test_is_only_optional_vitals_gap():
    assert is_only_optional_vitals_gap(["vitals"])
    assert is_only_optional_vitals_gap(["health_vitals", "vitals"])
    assert not is_only_optional_vitals_gap([])
    assert not is_only_optional_vitals_gap(["vitals", "diet-lifestyle-parameters"])


def test_filter_incomplete_for_essentials():
    assert filter_incomplete_for_essentials_completion(
        ["vitals", "physical-measurement"],
        type_code="1",
    ) == {"physical-measurement"}
    assert filter_incomplete_for_essentials_completion(
        ["vitals"],
        type_code="2",
    ) == {"vitals"}


def test_category_optional_for_essentials_completion():
    assert category_optional_for_essentials_completion("vitals")
    assert category_optional_for_essentials_completion("health_vitals")
    assert not category_optional_for_essentials_completion("blood-parameters")
