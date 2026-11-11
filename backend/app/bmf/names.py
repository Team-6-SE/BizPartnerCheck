"""Normalise company names for the "possible match" comparison (S4.3).

Only an exact match of the normalised names counts. We remove what differs between
two spellings of the same company, but nothing that would make different companies
look the same:

    "MUSTER BAU GMBH"          -> "muster bau"
    "Muster-Bau Ges.m.b.H."    -> "muster bau"
    "Müller & Söhne KG"        -> "mueller und soehne"
    "Muster GmbH in Liqu."     -> "muster"
"""

import re
import unicodedata

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})

# Legal forms (Austria, Germany and frequent neighbours), written without dots and
# spaces, because those are removed first. Only removed at the end of the name.
_LEGAL_FORMS = (
    "gesellschaft mit beschraenkter haftung",
    "gesmbh",
    "gmbh",
    "gmbh und co kg",
    "gmbh co kg",
    "und co kg",
    "co kg",
    "kg",
    "og",
    "oeg",
    "keg",
    "ag",
    "eu",
    "ek",
    "se",
    "ug",
    "ltd",
    "limited",
    "sro",
    "spol sro",
    "kft",
    "doo",
    "sp z oo",
    "srl",
    "bt",
)
_LEGAL_FORM_END = re.compile(
    r"(?:\s+(?:" + "|".join(sorted((re.escape(f) for f in _LEGAL_FORMS), key=len, reverse=True)) + r"))+$"
)

_STATE_END = re.compile(r"\s+in\s+(?:liquidation|liqu|abwicklung|konkurs|insolvenz)$")


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name).casefold().translate(_UMLAUTS)
    text = text.replace("&", " und ").replace("+", " und ")
    # Dots inside legal forms ("Ges.m.b.H.", "e.U.") disappear, other punctuation
    # becomes a space ("Muster-Bau" = "Muster Bau").
    text = text.replace(".", "")
    text = "".join(c if c.isalnum() else " " for c in text)
    # Remaining accents (é, č, ő) are compared without them.
    text = "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )
    text = " ".join(text.split())
    # "... GmbH in Liquidation" is the same company as "... GmbH".
    text = _STATE_END.sub("", text)
    stripped = _LEGAL_FORM_END.sub("", text).strip()
    # A name that is only a legal form keeps it (nothing left to compare otherwise).
    return stripped or text
