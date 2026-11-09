import pytest

from app.partners.register import (
    InvalidRegisterNumber,
    normalize_register_number,
    validate_register_number,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("123456a", "123456a"),
        ("FN 123456a", "123456a"),
        ("fn123456A", "123456a"),
        ("FN 123.456 a", "123456a"),
        ("FN 123456-a", "123456a"),
        ("  123456 A  ", "123456a"),
        ("1a", "1a"),
        ("FN 33209m", "33209m"),
        # Leading zeros are dropped, so one company cannot be saved twice.
        ("FN 012345b", "12345b"),
        ("000001z", "1z"),
    ],
)
def test_valid_register_numbers_are_normalised(raw: str, expected: str) -> None:
    assert validate_register_number(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "FN",
        "123456",  # letter missing
        "a123456",  # letter in front
        "1234567a",  # more than 6 digits
        "123456ab",  # two letters
        "0a",  # no number
        "12 34 56 7a",
        "123456ä",  # not a letter a-z
        "ATU12345678",  # a VAT number in the wrong field
    ],
)
def test_invalid_register_numbers_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidRegisterNumber):
        validate_register_number(raw)


def test_error_message_shows_an_example() -> None:
    with pytest.raises(InvalidRegisterNumber, match="123456a"):
        validate_register_number("12345678")


def test_very_long_input_is_rejected_quickly() -> None:
    with pytest.raises(InvalidRegisterNumber, match="at most 6 digits"):
        validate_register_number("1" * 500 + "a")


def test_normalize_keeps_unknown_characters_for_the_error_message() -> None:
    assert normalize_register_number("FN 12/34 5x") == "12345x"
    assert normalize_register_number("12#3a") == "12#3a"