"""Tests for deliverable contact heuristics."""

from modules.notifications.deliverable_contact import is_deliverable_email


def test_deliverable_real_email():
    assert is_deliverable_email("pratheek.fitnastic@gmail.com") is True


def test_non_deliverable_example_com():
    assert is_deliverable_email("adi.family@example.com") is False
    assert is_deliverable_email("bot-12@example.com") is False


def test_non_deliverable_empty_or_malformed():
    assert is_deliverable_email(None) is False
    assert is_deliverable_email("") is False
    assert is_deliverable_email("not-an-email") is False