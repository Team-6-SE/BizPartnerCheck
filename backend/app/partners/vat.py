"""VAT number (UID) format check.

Only the *format* is checked here (country code + number, e.g. ATU12345678).
Whether the number really exists is checked later against VIES.
"""

import re

# Number part per EU country code, as used by VIES. "EL" is Greece, "XI" Northern Ireland.
_NUMBER_PATTERNS: dict[str, str] = {
    "AT": r"U\d{8}",
    "BE": r"[01]\d{9}",
    "BG": r"\d{9,10}",
    "CY": r"\d{8}[A-Z]",
    "CZ": r"\d{8,10}",
    "DE": r"\d{9}",
    "DK": r"\d{8}",
    "EE": r"\d{9}",
    "EL": r"\d{9}",
    "ES": r"[A-Z0-9]\d{7}[A-Z0-9]",
    "FI": r"\d{8}",
    "FR": r"[0-9A-HJ-NP-Z]{2}\d{9}",
    "HR": r"\d{11}",
    "HU": r"\d{8}",
    "IE": r"\d[0-9A-Z+*]\d{5}[A-Z]{1,2}",
    "IT": r"\d{11}",
    "LT": r"\d{9}|\d{12}",
    "LU": r"\d{8}",
    "LV": r"\d{11}",
    "MT": r"\d{8}",
    "NL": r"\d{9}B\d{2}",
    "PL": r"\d{10}",
    "PT": r"\d{9}",
    "RO": r"\d{2,10}",
    "SE": r"\d{12}",
    "SI": r"\d{8}",
    "SK": r"\d{10}",
    "XI": r"\d{9}|\d{12}|GD\d{3}|HA\d{3}",
}

EXAMPLE = "ATU12345678"
# The longest EU VAT number (country code included) has 14 characters.
MAX_LENGTH = 14


class InvalidVatNumber(ValueError):
    """The VAT number does not have a valid format. The message is shown to the user."""


def normalize_vat_number(raw: str) -> str:
    """Upper case, without spaces, dots and dashes: 'atu 123.456-78' -> 'ATU12345678'."""
    return re.sub(r"[\s.\-]", "", raw).upper()


def validate_vat_number(raw: str) -> str:
    """Return the normalised VAT number or raise InvalidVatNumber."""
    vat = normalize_vat_number(raw)
    if not vat:
        raise InvalidVatNumber(f"Please enter a VAT number, e.g. {EXAMPLE}.")
    if len(vat) > MAX_LENGTH:
        raise InvalidVatNumber(
            f"A VAT number has at most {MAX_LENGTH} characters, e.g. {EXAMPLE}."
        )

    country, number = vat[:2], vat[2:]
    pattern = _NUMBER_PATTERNS.get(country)
    if pattern is None:
        raise InvalidVatNumber(
            f"'{country}' is not an EU country code. "
            f"Start with the country code, e.g. {EXAMPLE}."
        )
    # re.ASCII: only 0-9 count as digits (not e.g. Arabic-Indic digits).
    if not re.fullmatch(pattern, number, flags=re.ASCII):
        raise InvalidVatNumber(
            f"'{vat}' is not a valid {country} VAT number. "
            f"Expected country code + number, e.g. {EXAMPLE}."
        )
    return vat
