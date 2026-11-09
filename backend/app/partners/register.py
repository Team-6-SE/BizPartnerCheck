"""Company register number (Firmenbuchnummer, FN) format check.

An Austrian company register number is up to 6 digits followed by one check letter,
written e.g. "FN 123456a". Only the *format* is checked here; whether the company
really exists is checked later against the Firmenbuch (story S4.5).

Stored form: digits without leading zeros + lower-case letter, e.g. "123456a".
"""

import re

EXAMPLE = "123456a"
# "FN" + up to 6 digits + letter, with some spaces: anything longer is surely wrong.
MAX_INPUT_LENGTH = 30


class InvalidRegisterNumber(ValueError):
    """The company register number has a wrong format. The message is shown to the user."""


def normalize_register_number(raw: str) -> str:
    """Lower case, without spaces, dots, dashes, slashes and the "FN" prefix.

    'FN 123.456 A' -> '123456a', 'fn012345b' -> '12345b' (leading zeros removed, so
    the same company cannot be saved twice in two spellings).
    """
    value = re.sub(r"[\s.\-/]", "", raw).lower()
    if value.startswith("fn"):
        value = value[2:]
    match = re.fullmatch(r"0*(\d+)([a-z])", value, flags=re.ASCII)
    if match:
        value = match.group(1) + match.group(2)
    return value


def validate_register_number(raw: str) -> str:
    """Return the normalised company register number or raise InvalidRegisterNumber."""
    if len(raw) > MAX_INPUT_LENGTH:
        raise InvalidRegisterNumber(
            f"A company register number has at most 6 digits and a letter, e.g. {EXAMPLE}."
        )
    value = normalize_register_number(raw)
    if not value:
        raise InvalidRegisterNumber(
            f"Please enter a company register number, e.g. {EXAMPLE}."
        )
    # re.ASCII: only 0-9 count as digits. The number never starts with 0 after normalising.
    if not re.fullmatch(r"[1-9]\d{0,5}[a-z]", value, flags=re.ASCII):
        raise InvalidRegisterNumber(
            f"'{raw.strip()}' is not a valid company register number. "
            f"Expected up to 6 digits and a letter, e.g. {EXAMPLE} or FN {EXAMPLE}."
        )
    return value