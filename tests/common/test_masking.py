"""Unit tests for PII masking helpers."""

from common.masking import looks_masked, mask_email, mask_phone


def test_mask_phone_keeps_last_four():
    assert mask_phone("8176457985") == "******7985"
    assert mask_phone("9600004773") == "******4773"
    assert mask_phone(None) is None
    assert mask_phone("") == ""
    assert mask_phone("1234") == "1234"


def test_mask_email_keeps_first_and_last_three_of_local():
    assert mask_email("sandeeprairai199@gmail.com") == "s************199@gmail.com"
    assert mask_email("pratheek.fitnastic@gmail.com") == "p**************tic@gmail.com"
    assert mask_email("jane.doe@example.com") == "j****doe@example.com"
    assert mask_email("ab@x.com") == "**@x.com"
    assert mask_email(None) is None


def test_looks_masked():
    assert looks_masked("******7985") is True
    assert looks_masked("s************199@gmail.com") is True
    assert looks_masked("8176457985") is False
    assert looks_masked(None) is False
