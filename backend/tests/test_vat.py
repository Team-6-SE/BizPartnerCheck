import pytest

from app.partners.vat import InvalidVatNumber, normalize_vat_number, validate_vat_number


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("ATU12345678", "ATU12345678"),
        ("atu12345678", "ATU12345678"),
        (" ATU 123 456 78 ", "ATU12345678"),
        ("AT-U12.345.678", "ATU12345678"),
        ("DE123456789", "DE123456789"),
        ("NL123456789B01", "NL123456789B01"),
        ("FR1A123456789", "FR1A123456789"),
        ("ESX1234567Z", "ESX1234567Z"),
        ("EL123456789", "EL123456789"),
    ],
)
def test_valid_vat_numbers_are_normalised(raw: str, expected: str) -> None:
    assert validate_vat_number(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "12345678",  # no country code
        "U12345678",  # no country code
        "XX123456789",  # not an EU country
        "GR123456789",  # Greece uses EL in VIES
        "AT12345678",  # Austrian numbers start with U
        "ATU1234567",  # one digit too short
        "ATU123456789",  # one digit too long
        "DE12345678",  # too short
        "DE12345678A",  # letter not allowed
        "ATU١٢٣٤٥٦٧٨",  # non-ASCII digits
        "AT" + "U" * 500,  # far too long
    ],
)
def test_invalid_vat_numbers_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidVatNumber):
        validate_vat_number(raw)


def test_normalize_keeps_other_characters() -> None:
    assert normalize_vat_number("at u123/45") == "ATU123/45"


def test_long_input_is_not_echoed_in_the_message() -> None:
    with pytest.raises(InvalidVatNumber) as error:
        validate_vat_number("AT" + "X" * 500)

    assert len(str(error.value)) < 100
