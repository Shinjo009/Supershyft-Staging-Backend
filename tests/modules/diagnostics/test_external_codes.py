"""Tests for diagnostic external code helpers."""

from modules.diagnostics.external_codes import healthians_package_deal_id, healthians_product_deal_type_id


def test_healthians_package_deal_id_from_string_code():
    assert healthians_package_deal_id("101") == "package_101"


def test_healthians_package_deal_id_empty_defaults_to_zero():
    assert healthians_package_deal_id(None) == "package_0"
    assert healthians_package_deal_id("") == "package_0"


def test_healthians_product_deal_type_id():
    assert healthians_product_deal_type_id("42") == 42
