"""Firmenbuch (Austrian company register): does the company exist and is it active? (S4.5)

We ask the JustizOnline "FBW-WebServices (HVD)" (interface description v1.3) for a
short extract ("Kurzinformation") of the company register number (FN):

    POST https://justizonline.gv.at/jop/api/at.gv.justiz.fbw/ws
    X-API-KEY: <token from JustizOnline>          FIRMENBUCH_API_KEY, never stored
    Content-Type: application/soap+xml;charset=UTF-8

    <aus:AUSZUG_V2_REQUEST>
      <aus:FNR>123456a</aus:FNR>                   our stored form, e.g. "123456a"
      <aus:STICHTAG>2026-11-19</aus:STICHTAG>      today in Vienna (not in the future)
      <aus:UMFANG>Kurzinformation</aus:UMFANG>     the only extent HVD allows
    </aus:AUSZUG_V2_REQUEST>

From the answer we keep only what the check needs (data minimisation): name, address,
seat and legal form of the company, its current legal facts (Rechtstatsachen, e.g.
insolvency), and for every current function (managing director, shareholder, ...) the
person's name, role and start date. Birth dates, private addresses and citizenship of
persons are not read and never stored.

    registered, no flag                 -> OK
    deleted, insolvency, liquidation    -> FINDING (the flag is shown)
    only insolvency proceedings that ended -> REVIEW
    a fault that clearly says "no such FN" -> FINDING ("not in the register")
    no FN (e.g. foreign partner)        -> NOT_APPLICABLE (the check run does not ask)
    no API key, refused, not reachable,
    any other fault or answer we do not understand -> ERROR

When in doubt the result is ERROR ("could not check"), never a FINDING that is not
there: a wrong "this company does not exist" is worse than no answer.

Details and the open points to verify with the real service: docs/firmenbuch.md
"""

import os
import re
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import httpx2 as httpx
from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from app.adapters.base import (
    BAD_RESPONSE,
    NO_ANSWER_IN_TIME,
    NOT_REACHABLE,
    CheckStatus,
    CheckSubject,
    Interpretation,
    Scenario,
    SourceAdapter,
)
from app.adapters.fake import adapter_setting, with_fake_from_env

SOURCE = "FIRMENBUCH"
DEFAULT_BASE_URL = "https://justizonline.gv.at/jop/api/at.gv.justiz.fbw/ws"
REQUEST_NAMESPACE = "ns://firmenbuch.justiz.gv.at/Abfrage/v2/AuszugRequest"
SOAP12_NAMESPACE = "http://www.w3.org/2003/05/soap-envelope"
API_KEY_HEADER = "X-API-KEY"
EXTENT = "Kurzinformation"

# Our own error codes for this source.
NO_API_KEY = "NO_API_KEY"  # FIRMENBUCH_API_KEY is not set: nothing is sent
SOAP_FAULT = "SOAP_FAULT"  # the service refused the request
INVALID_NUMBER = "INVALID_NUMBER"  # the service did not accept the FN as a number

# The register is Austrian, so "today" is the day in Vienna (a later day is refused).
VIENNA = ZoneInfo("Europe/Vienna")

# --- reading fault texts ---------------------------------------------------------------
# The interface description shows no fault for an FN that does not exist, so we cannot
# know its exact wording (to verify with the real service, docs/firmenbuch.md). Only a
# text that names the company or the number AND says it does not exist counts as "not
# found"; any other fault, e.g. "Unbekannter Fehler", stays an error.
_NUMBER_OR_COMPANY = re.compile(
    r"\b(?:firma|firmenbuchnummer|fnr|fn|rechtsträger|unternehmen|company)\b",
    re.IGNORECASE,
)
_DOES_NOT_EXIST = re.compile(
    r"\b(?:nicht gefunden|nicht vorhanden|existiert nicht|nicht existent"
    r"|not found|does not exist)\b"
    r"|\bkein(?:e|en)? (?:firma|eintrag|daten|treffer)\b",
    re.IGNORECASE,
)
# Faults about our request (the key, the reference date): never "not found".
_ABOUT_REQUEST = re.compile(r"\b(?:key|schlüssel|parameter|stichtag)\b", re.IGNORECASE)
# The documented fault for a malformed number: "Firmenbuchnummer ist ungültig! (max. 6
# Ziffern plus Prüfzeichen)". If our format were wrong, every check would get it, so
# it is an error to look at, not a finding about the partner.
_INVALID_NUMBER = re.compile(
    r"\b(?:firmenbuchnummer|fnr|fn)\b.*\bungültig|\bungültige (?:firmenbuchnummer|fnr)\b",
    re.IGNORECASE,
)


def fault_kind(reason: str | None) -> str:
    """'notFound', INVALID_NUMBER or SOAP_FAULT for the text of a SOAP fault."""
    if not reason:
        return SOAP_FAULT
    if _INVALID_NUMBER.search(reason):
        return INVALID_NUMBER
    if (
        _NUMBER_OR_COMPANY.search(reason)
        and _DOES_NOT_EXIST.search(reason)
        and not _ABOUT_REQUEST.search(reason)
    ):
        return "notFound"
    return SOAP_FAULT


# --- reading legal facts (Rechtstatsachen) ---------------------------------------------
# Every legal fact has a CODE, but the HVD description does not list the codes, so for
# now we read the German text. UNVERIFIED: these rules follow the usual register
# wording and must be checked with real extracts (docs/firmenbuch.md); once the codes
# are known, matching on them is better.
#
# Whole words only, read clause by clause, and "Löschung" / "Auflösung" only when they
# are about the company: "Löschung der Prokura" (a signing authority removed) or
# "Abwicklungsservice" are not flags.
_COMPANY = r"(?:firma|gesellschaft|rechtsträger|unternehmen)\b"
# "Löschung der Prokura", "Auflösung der Zweigniederlassung": about something else.
_OF_SOMETHING_ELSE = rf"(?!\s+(?:der|des|von|eines|einer)\s+(?!{_COMPANY}))"
_INSOLVENCY = re.compile(
    r"\b(?:konkurs|insolvenz|sanierungsverfahren|schuldenregulierung"
    r"|ausgleichsverfahren|zahlungsunfähig)",
    re.IGNORECASE,
)
_FLAG_WORDS = {
    "deleted": re.compile(
        rf"\blöschung\b{_OF_SOMETHING_ELSE}|\b{_COMPANY}.*\bgelöscht\b", re.IGNORECASE
    ),
    "insolvency": _INSOLVENCY,
    "liquidation": re.compile(
        rf"\bliquidation\b|\bin liqu\b|\babwicklung\b|\bauflösung\b{_OF_SOMETHING_ELSE}"
        rf"|\b{_COMPANY}.*\baufgelöst\b",
        re.IGNORECASE,
    ),
}
# In the name only the suffix the law asks for during liquidation ("in Liqu.").
_NAME_IN_LIQUIDATION = re.compile(r"\bin liquidation\b|\bin liqu\b", re.IGNORECASE)
# Insolvency proceedings that are over (the company may be active again) ...
_ENDED = re.compile(
    r"\b(?:aufgehoben|aufhebung|beendet|beendigung|eingestellt|einstellung"
    r"|abgeschlossen|rechtskräftig bestätigt)\b",
    re.IGNORECASE,
)
# ... but not "mangels Kostendeckung": then the company had too little money even for
# the proceedings, which is no good news.
_NO_ASSETS = re.compile(r"\bmangels\b", re.IGNORECASE)
# Clauses: split at ";", line breaks and full stops that end a sentence (not in dates).
_CLAUSE_END = re.compile(r"[;\n]|\.(?=\s+[A-ZÄÖÜ])")


def _clauses(text: str) -> list[str]:
    return [part.strip() for part in _CLAUSE_END.split(text) if part.strip()]


def _insolvency_ended(text: str) -> bool:
    """True only if every clause about insolvency itself says it has ended.

    "Konkurs aufgehoben" has ended; "Konkurs eröffnet; Vertretungsbefugnis aufgehoben"
    has not (the ending word belongs to another fact). When unsure: not ended.
    """
    about = [c for c in _clauses(text) if _INSOLVENCY.search(c)]
    return bool(about) and all(
        _ENDED.search(c) and not _NO_ASSETS.search(c) for c in about
    )


FLAG_LABELS = {
    "deleted": "deleted from the register",
    "insolvency": "insolvency proceedings",
    "liquidation": "dissolved / in liquidation",
}


def build_request(register_number: str, stichtag: date) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<soap:Envelope xmlns:soap="{SOAP12_NAMESPACE}" '
        f'xmlns:aus="{REQUEST_NAMESPACE}">'
        "<soap:Header/><soap:Body><aus:AUSZUG_V2_REQUEST>"
        f"<aus:FNR>{escape(register_number)}</aus:FNR>"
        f"<aus:STICHTAG>{stichtag.isoformat()}</aus:STICHTAG>"
        f"<aus:UMFANG>{EXTENT}</aus:UMFANG>"
        "</aus:AUSZUG_V2_REQUEST></soap:Body></soap:Envelope>"
    )


# --- reading the XML ---------------------------------------------------------------
# The service puts its own prefixes (ns6, ns7, ...) on elements and attributes, so we
# compare local names only.


def _name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _attr(element: ET.Element, name: str) -> str | None:
    for key, value in element.attrib.items():
        if key.rsplit("}", 1)[-1] == name:
            return value.strip() or None
    return None


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element if _name(child) == name]


def _child(element: ET.Element, name: str) -> ET.Element | None:
    found = _children(element, name)
    return found[0] if found else None


def _text(element: ET.Element | None, name: str) -> str | None:
    if element is None:
        return None
    child = _child(element, name)
    if child is None:
        return None
    return " ".join((child.text or "").split()) or None


def _texts(element: ET.Element, name: str) -> list[str]:
    return [
        " ".join((child.text or "").split())
        for child in _children(element, name)
        if (child.text or "").strip()
    ]


def _current(elements: list[ET.Element]) -> ET.Element | None:
    """The data group that is still valid ("AUFRECHT"), else the last one."""
    valid = [e for e in elements if _attr(e, "AUFRECHT") != "false"]
    if valid:
        return valid[-1]
    return elements[-1] if elements else None


def _code_text(element: ET.Element | None, name: str) -> dict[str, str | None] | None:
    if element is None:
        return None
    child = _child(element, name)
    if child is None:
        return None
    return {"code": _text(child, "CODE"), "text": _text(child, "TEXT")}


def _address(element: ET.Element | None) -> dict[str, Any] | None:
    if element is None:
        return None
    lines = _texts(element, "STELLE")
    if not lines:
        street = " ".join(
            part
            for part in (_text(element, "STRASSE"), _text(element, "HAUSNUMMER"))
            if part
        )
        extra = [
            f"{label} {value}"
            for label, value in (
                ("Stiege", _text(element, "STIEGE")),
                ("Tür", _text(element, "TUERNUMMER")),
            )
            if value
        ]
        lines = [", ".join([street, *extra])] if street else []
    return {
        "lines": lines,
        "postalCode": _text(element, "PLZ"),
        "city": _text(element, "ORT"),
        "country": _text(element, "STAAT"),
    }


def _legal_facts(parent: ET.Element) -> list[dict[str, Any]]:
    """The current legal facts (e.g. insolvency opened) of the company."""
    facts = []
    for group in _children(parent, "RECHTSTATSACHE"):
        for fact in _children(group, "RTS_DKZ50"):
            if _attr(fact, "AUFRECHT") == "false":
                continue
            texts = _texts(fact, "TEXT")
            for multi in _children(fact, "MULTI"):
                # Free text parts only; names and addresses in MULTI are not kept.
                texts += _texts(multi, "TXTZUS") + _texts(multi, "RTS")
            facts.append(
                {
                    "code": _text(fact, "CODE"),
                    "date": _text(fact, "DATUM_VOM"),
                    "text": " ".join(texts) or None,
                }
            )
    return facts


def _person_name(element: ET.Element | None) -> str | None:
    """Full name of a person, or the name of a company (e.g. a shareholder GmbH)."""
    if element is None:
        return None
    formatted = _texts(element, "NAME_FORMATIERT") or _texts(element, "BEZEICHNUNG")
    if formatted:
        return " ".join(formatted)
    first, last = _text(element, "VORNAME"), _text(element, "NACHNAME")
    # Older answers put the whole name (with title and first name) into NACHNAME.
    if last and first and first in last:
        return last
    parts = [_text(element, "TITELVOR"), first, last, _text(element, "TITELNACH")]
    return " ".join(p for p in parts if p) or None


def _persons(root: ET.Element) -> list[dict[str, Any]]:
    """Current functions with name, role and start date only (data minimisation)."""
    names = {}
    for person in _children(root, "PER"):
        number = _attr(person, "PNR")
        if number is not None:
            # Only the name: no birth date (GEBURTSDATUM), address or citizenship.
            names[number] = _person_name(_current(_children(person, "PE_DKZ02")))

    persons = []
    for function in _children(root, "FUN"):
        periods = _children(function, "FU_DKZ10")
        current = [
            p
            for p in periods
            if _attr(p, "AUFRECHT") != "false"
            and not _attr(p, "MIT_FIRMA_GELOESCHT_DURCH_VNR")
            and not _text(p, "DATBIS")
        ]
        if periods and not current:
            continue  # the function has ended
        number = _attr(function, "PNR")
        persons.append(
            {
                "name": names.get(number) if number is not None else None,
                "role": _attr(function, "FKENTEXT") or _attr(function, "FKEN"),
                "roleCode": _attr(function, "FKEN"),
                "since": _text(current[-1], "DATVON") if current else None,
            }
        )
    return persons


def _deleted_by(firma: ET.Element) -> str | None:
    """Number of the entry that deleted the company, if the company was deleted."""
    for element in firma.iter():
        number = _attr(element, "MIT_FIRMA_GELOESCHT_DURCH_VNR")
        if number:
            return number
    return None


def parse_response(body: str) -> dict[str, Any]:
    """The parts of the SOAP answer the check needs.

    Parsed with defusedxml (no entities, no DTD). Raises ET.ParseError if the body is
    not XML and DefusedXmlException if it tries entity or DTD tricks.
    """
    root = SafeET.fromstring(body)
    for element in root.iter():
        if _name(element) == "Fault":
            reason = next(
                (
                    " ".join((e.text or "").split())
                    for e in element.iter()
                    if _name(e) in ("Text", "faultstring") and (e.text or "").strip()
                ),
                None,
            )
            kind = fault_kind(reason)
            if kind == "notFound":
                return {"notFound": True, "fault": reason}
            return {"error": kind, "fault": reason}

    answer = next((e for e in root.iter() if _name(e) == "AUSZUG_V2_RESPONSE"), None)
    if answer is None:
        return {"error": BAD_RESPONSE, "message": "no AUSZUG_V2_RESPONSE"}
    firma = _child(answer, "FIRMA")
    if firma is None:
        # The schema requires FIRMA: an answer without it is broken, it does not
        # prove that the company does not exist.
        return {"error": BAD_RESPONSE, "message": "AUSZUG_V2_RESPONSE without FIRMA"}

    name_group = _current(_children(firma, "FI_DKZ02"))
    name_lines = _texts(name_group, "BEZEICHNUNG") if name_group is not None else []
    seat_group = _current(_children(firma, "FI_DKZ06"))
    return {
        "register": {
            "fnr": _attr(answer, "FNR"),
            "stichtag": _attr(answer, "STICHTAG"),
            "queriedAt": _attr(answer, "ABFRAGEZEITPUNKT"),
            "checksum": _attr(answer, "PRUEFSUMME"),
        },
        "company": {
            "name": " ".join(name_lines) or None,
            "address": _address(_current(_children(firma, "FI_DKZ03"))),
            "seat": _text(seat_group, "SITZ"),
            "legalForm": _code_text(
                _current(_children(firma, "FI_DKZ07")), "RECHTSFORM"
            ),
            "deletedByEntry": _deleted_by(firma),
        },
        "legalFacts": _legal_facts(firma),
        "persons": _persons(answer),
    }


# --- what the answer means ----------------------------------------------------------


def status_flags(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Deletion, insolvency and liquidation found in the answer, with the source text."""
    company = raw.get("company") if isinstance(raw.get("company"), dict) else {}
    flags: list[dict[str, Any]] = []
    if company.get("deletedByEntry"):
        flags.append({"kind": "deleted", "text": None, "date": None, "ended": False})
    name = company.get("name") or ""
    if _NAME_IN_LIQUIDATION.search(name):
        flags.append(
            {"kind": "liquidation", "text": name, "date": None, "ended": False}
        )
    for fact in raw.get("legalFacts") or []:
        if not isinstance(fact, dict):
            continue
        text = fact.get("text") or ""
        clauses = _clauses(text)
        for kind, words in _FLAG_WORDS.items():
            if not any(words.search(clause) for clause in clauses):
                continue
            if kind == "deleted" and any(f["kind"] == "deleted" for f in flags):
                continue
            flags.append(
                {
                    "kind": kind,
                    "text": text,
                    "date": fact.get("date"),
                    "ended": kind == "insolvency" and _insolvency_ended(text),
                }
            )
            break
    return flags


def address_text(raw: dict[str, Any]) -> str | None:
    """The company's address in two lines, e.g. 'Kärntner Straße 337\\n8054 Graz'."""
    company = raw.get("company")
    address = company.get("address") if isinstance(company, dict) else None
    if not isinstance(address, dict):
        return None
    place = " ".join(p for p in (address.get("postalCode"), address.get("city")) if p)
    lines = [*(address.get("lines") or []), place]
    return "\n".join(line for line in lines if line) or None


def company_name(raw: dict[str, Any]) -> str | None:
    company = raw.get("company")
    return company.get("name") if isinstance(company, dict) else None


def legal_form(raw: dict[str, Any]) -> str | None:
    company = raw.get("company")
    form = company.get("legalForm") if isinstance(company, dict) else None
    if not isinstance(form, dict):
        return None
    return form.get("text") or form.get("code")


def seat(raw: dict[str, Any]) -> str | None:
    company = raw.get("company")
    if not isinstance(company, dict):
        return None
    address = company.get("address") if isinstance(company.get("address"), dict) else {}
    return company.get("seat") or address.get("city")


def register_number(raw: dict[str, Any]) -> str | None:
    """FN as the register writes it ("58468 h"), else the number we asked for."""
    register = raw.get("register") if isinstance(raw.get("register"), dict) else {}
    checked = raw.get("checked") if isinstance(raw.get("checked"), dict) else {}
    return register.get("fnr") or checked.get("fnr")


class FirmenbuchAdapter(SourceAdapter):
    source = SOURCE

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        **options: Any,
    ) -> None:
        super().__init__(**options)
        self.base_url = base_url
        self._api_key = (api_key or "").strip() or None
        # Tests pass a fake transport, so they never need the internet.
        self._transport = transport

    def query(self, subject: CheckSubject, timeout: float) -> dict[str, Any]:
        number = subject.register_number
        if not number:
            # Check runs skip partners without FN before; this only guards against bugs.
            raise ValueError("The Firmenbuch needs a company register number")

        stichtag = self._now().astimezone(VIENNA).date()
        answer: dict[str, Any] = {
            "stichtag": stichtag.isoformat(),
            "checked": {"fnr": number},
        }
        if self._api_key is None:
            # Without the token JustizOnline refuses every call: do not send any.
            answer["error"] = NO_API_KEY
            return answer

        with httpx.Client(transport=self._transport) as client:
            response = client.post(
                self.base_url,
                content=build_request(number, stichtag).encode("utf-8"),
                headers={
                    "Content-Type": "application/soap+xml;charset=UTF-8",
                    API_KEY_HEADER: self._api_key,
                },
                timeout=timeout,
            )
        try:
            parsed = parse_response(response.text)
        except (ET.ParseError, DefusedXmlException):
            # E.g. an HTML error page (429, 401); a short excerpt is enough as evidence.
            parsed = {"error": BAD_RESPONSE, "message": response.text[:300]}

        answer.update(parsed)
        if response.status_code >= 400:
            answer["httpStatus"] = response.status_code
        return answer

    def interpret(self, raw: dict[str, Any]) -> Interpretation:
        error = raw.get("error")
        if error == NO_API_KEY:
            return Interpretation(CheckStatus.ERROR)
        if raw.get("notFound") is True:
            # Checked before the HTTP status: a fault may come with HTTP 500.
            return Interpretation(CheckStatus.FINDING)
        if error in (SOAP_FAULT, INVALID_NUMBER):
            # The service refused our request: asking again would not help.
            return Interpretation(CheckStatus.ERROR)
        http_status = raw.get("httpStatus")
        if isinstance(http_status, int) and http_status >= 400:
            # 429 (too many requests) and 5xx may go away; 401/403 (key) will not.
            temporary = http_status >= 500 or http_status == 429
            return Interpretation(CheckStatus.ERROR, try_again=temporary)
        if error or not company_name(raw):
            return Interpretation(CheckStatus.ERROR)

        flags = status_flags(raw)
        if any(not flag["ended"] for flag in flags):
            return Interpretation(CheckStatus.FINDING)
        if flags:
            return Interpretation(CheckStatus.REVIEW)
        return Interpretation(CheckStatus.OK)

    def describe(self, status: CheckStatus, raw: dict[str, Any]) -> str:
        return describe(status, raw)

    def sample_answer(
        self, scenario: Scenario, subject: CheckSubject
    ) -> dict[str, Any]:
        stichtag = self._now().astimezone(VIENNA).date().isoformat()
        number = subject.register_number or "123456a"
        facts = (
            [
                {
                    "code": "KONK",
                    "date": stichtag,
                    "text": "Konkurs eröffnet (fake Firmenbuch)",
                }
            ]
            if scenario == Scenario.FINDING
            else []
        )
        return {
            "stichtag": stichtag,
            "checked": {"fnr": number},
            "register": {
                "fnr": number,
                "stichtag": stichtag,
                "queriedAt": None,
                "checksum": None,
            },
            "company": {
                "name": "Muster Bau GmbH (fake Firmenbuch)",
                "address": {
                    "lines": ["Rathausplatz 6"],
                    "postalCode": "3100",
                    "city": "St. Pölten",
                    "country": "AUT",
                },
                "seat": "St. Pölten",
                "legalForm": {
                    "code": "GES",
                    "text": "Gesellschaft mit beschränkter Haftung",
                },
                "deletedByEntry": None,
            },
            "legalFacts": facts,
            "persons": [
                {
                    "name": "Maria Muster",
                    "role": "GESCHÄFTSFÜHRER/IN (handelsrechtlich)",
                    "roleCode": "GF",
                    "since": "2020-01-15",
                },
                {
                    "name": "Muster Holding GmbH",
                    "role": "GESELLSCHAFTER/IN",
                    "roleCode": "GS",
                    "since": "2020-01-15",
                },
            ],
        }


def _day(value: Any) -> str:
    """'2026-11-19' -> ' as of 19 Nov 2026', or '' if unknown."""
    try:
        parsed = date.fromisoformat(str(value)[:10])
    except ValueError:
        return ""
    return f" as of {parsed.day} {parsed:%b %Y}"


def _flag_text(flag: dict[str, Any]) -> str:
    label = FLAG_LABELS.get(flag.get("kind", ""), "a register note")
    text = flag.get("text")
    if text and text != label:
        return f'{label} ("{text}")'
    return label


_ERROR_MESSAGES = {
    NO_ANSWER_IN_TIME: "The Firmenbuch did not answer in time.",
    NOT_REACHABLE: "The Firmenbuch could not be reached.",
}


def describe(status: CheckStatus, raw: dict[str, Any]) -> str:
    """One sentence for people: what the result means and what to do."""
    as_of = _day(raw.get("stichtag"))
    number = register_number(raw)
    fn = f"FN {number}" if number else "this company register number"
    name = company_name(raw)

    if status == CheckStatus.FINDING and raw.get("notFound"):
        return (
            f"The Firmenbuch has no company with {fn}{as_of}. Please check the number "
            "with the partner: a company that is not registered must not use an FN."
        )
    if status == CheckStatus.OK:
        place = seat(raw)
        parts = (legal_form(raw), f"seat {place}" if place else None)
        details = ", ".join(p for p in parts if p)
        return (
            f"{name} is registered in the Firmenbuch under {fn}{as_of}"
            f"{f' ({details})' if details else ''}. No deletion, insolvency or "
            "liquidation is recorded."
        )
    if status in (CheckStatus.FINDING, CheckStatus.REVIEW):
        flags = status_flags(raw)
        active = [f for f in flags if not f["ended"]]
        if status == CheckStatus.FINDING and active:
            listed = "; ".join(_flag_text(f) for f in active)
            return (
                f"The Firmenbuch records for {name} ({fn}){as_of}: {listed}. "
                "Please check carefully before doing business with this partner."
            )
        listed = "; ".join(_flag_text(f) for f in flags) or "a register note"
        return (
            f"The Firmenbuch records ended proceedings for {name} ({fn}){as_of}: "
            f"{listed}. The company is registered; please review the entry."
        )

    error = raw.get("error")
    if error == NO_API_KEY:
        return (
            "The Firmenbuch check is not set up on this server yet (no API key). "
            "The result was not confirmed."
        )
    if error == INVALID_NUMBER:
        reason = raw.get("fault")
        detail = f' ("{reason}")' if reason else ""
        return (
            f"The Firmenbuch did not accept {fn} as a company register number{detail}. "
            "The result was not confirmed. Please check the number with the partner."
        )
    if error == SOAP_FAULT:
        reason = raw.get("fault")
        detail = f": {reason}" if reason else ""
        return f"The Firmenbuch rejected the request{detail}. The result was not confirmed."
    http_status = raw.get("httpStatus")
    if http_status in (401, 403):
        return (
            "The Firmenbuch refused our API key. Please ask the administrator to "
            "renew it. The result was not confirmed."
        )
    if http_status == 429:
        return (
            "The Firmenbuch is busy (too many requests). The result was not "
            "confirmed. Please try again in a few minutes."
        )
    reason = _ERROR_MESSAGES.get(error, "The Firmenbuch could not be checked.")
    return f"{reason} The result was not confirmed. Please try again later."


def is_enabled() -> bool:
    """Check runs ask the Firmenbuch when the API key is set or a fake is chosen."""
    return bool(os.environ.get("FIRMENBUCH_API_KEY", "").strip()) or (
        adapter_setting(SOURCE) is not None
    )


def get_firmenbuch_adapter() -> SourceAdapter:
    """FastAPI dependency.

    FIRMENBUCH_API_KEY is the token from JustizOnline (secret: .env / deploy.env only).
    FIRMENBUCH_BASE_URL can point to another endpoint; FIRMENBUCH_ADAPTER=fake-... uses
    a fake without any network (see app/adapters/fake.py).
    """
    return with_fake_from_env(
        FirmenbuchAdapter(
            os.environ.get("FIRMENBUCH_BASE_URL") or DEFAULT_BASE_URL,
            os.environ.get("FIRMENBUCH_API_KEY"),
        )
    )
