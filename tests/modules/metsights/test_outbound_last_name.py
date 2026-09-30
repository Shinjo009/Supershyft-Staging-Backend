from modules.metsights.service import outbound_last_name


def test_outbound_last_name_blank_becomes_hyphen():
    assert outbound_last_name(None) == "-"
    assert outbound_last_name("") == "-"
    assert outbound_last_name("   ") == "-"


def test_outbound_last_name_preserves_value():
    assert outbound_last_name("Shanker") == "Shanker"
    assert outbound_last_name("  R  ") == "R"
