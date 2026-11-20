"""GISA (Austrian business licence register): which trade licences does the partner hold? (S4.6)

We ask the public GISA interface, version 2 ("GISA Öffentliche Schnittstelle Version 2",
BMDW 2021, with its XML structure file and SoapUI examples), in two steps:

1. SearchPersonJur(Apikey, Firmenbuchnummer, SearchHistorisch=true, ...)
   -> every licence (Gewerbe) of the company, also ended ones, as GISA numbers
2. GetGewerbeV2(Apikey, GISAZahl) for each licence (at most MAX_LICENCES)
   -> trade, key, dates, suspension, location and the responsible person
      (gewerberechtlicher Geschäftsführer)

In the detail every part has its current entry as a direct child (<BerechtigungDaten>
<Berechtigung>) and older or ended entries under <Historie>. A licence without a current
<Berechtigung> has ended.

The API key (GISA_API_KEY) is personal: every query is logged for seven years under the
key holder's name. It is never stored in a result.

    at least one active licence               -> OK (all licences listed)
    licences, but none active (ended, ruhend) -> FINDING ("no active licence")
    no licence at all                         -> FINDING ("no licence")
    only licences whose status is unclear     -> REVIEW
    no company register number                -> NOT_APPLICABLE (the run does not ask)
    no API key, key refused, not reachable    -> ERROR

Data minimisation: for persons (owner, responsible person) only the name and the start
date are kept; birth dates and GISA person IDs are not read.
"""

import os
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import httpx2 as httpx

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

SOURCE = "GISA"
# The WSDL names another address; the documentation says to use this one.
DEFAULT_BASE_URL = "https://www.gisa.gv.at/gisa-svc-public/GisaPublicV2.svc/soap"
SERVICE_NAMESPACE = "http://gisa.wien.gv.at/public_svc/V2"
# From the WSDL (GisaPublicV2.svc?SingleWSDL).
SOAP_ACTION = SERVICE_NAMESPACE + "/IGisaPublic/{operation}"
# Detail calls per check. Big companies have more licences (most of them ended); the
# rest is listed with the hit list data only.
MAX_LICENCES = 15

# Our own error codes for this source.
NO_API_KEY = "NO_API_KEY"  # GISA_API_KEY is not set: nothing is sent
GISA_ERROR = "GISA_ERROR"  # GISA answered with Returncode ERROR
SOAP_FAULT = "SOAP_FAULT"

# Message codes of the GISA interface (MeldungListe/Meldung/Code).
KEY_INVALID = "300"  # API key not found or expired
UNEXPECTED = "310"  # unexpected error on the GISA side
NOT_FOUND = "1000"  # GISA number not found or invalid

VIENNA = ZoneInfo("Europe/Vienna")

ACTIVE = "active"
SUSPENDED = "suspended"
ENDED = "ended"
UNKNOWN = "unknown"

STATE_LABELS = {
    ACTIVE: "active",
    SUSPENDED: "suspended (ruhend)",
    ENDED: "ended",
    UNKNOWN: "status unclear",
}


# --- requests ----------------------------------------------------------------------------


def _envelope(operation: str, fields: list[tuple[str, str]]) -> str:
    """Like the ministry's SoapUI examples: <v2:Op><v2:input> with unqualified fields."""
    body = "".join(f"<{name}>{escape(value)}</{name}>" for name, value in fields)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:v2="{SERVICE_NAMESPACE}">'
        f"<s:Body><v2:{operation}><v2:input>{body}</v2:input></v2:{operation}>"
        "</s:Body></s:Envelope>"
    )


def build_search_request(api_key: str, register_number: str) -> str:
    """All licences of the company with this FN, also ended ones (historisch).

    The order of the fields matters: the service (WCF) ignores fields that are not in
    the order of the WSDL (Apikey first, then alphabetical).
    """
    return _envelope(
        "SearchPersonJur",
        [
            ("Apikey", api_key),
            ("Firmenbuchnummer", register_number),
            ("SearchAuslVermittler", "false"),
            ("SearchHistorisch", "true"),
            ("SearchPhonetisch", "false"),
        ],
    )


def build_detail_request(api_key: str, gisa_number: str) -> str:
    return _envelope("GetGewerbeV2", [("Apikey", api_key), ("GISAZahl", gisa_number)])


# --- reading the XML ---------------------------------------------------------------------
# The answer puts the SOAP parts in a namespace and the data in none; we compare local
# names only.


def _name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _child(element: ET.Element | None, *path: str) -> ET.Element | None:
    """The first element along this path of direct children, or None."""
    for name in path:
        if element is None:
            return None
        element = next((c for c in element if _name(c) == name), None)
    return element


def _text(element: ET.Element | None, *path: str) -> str | None:
    found = _child(element, *path)
    if found is None:
        return None
    return " ".join((found.text or "").split()) or None


def _day(value: str | None) -> str | None:
    """'2019-02-04T00:00:00' -> '2019-02-04'."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def _current_or_latest(
    group: ET.Element | None, name: str
) -> tuple[ET.Element | None, bool]:
    """The current entry of a <...Daten> group, else the newest one from <Historie>.

    Returns the entry and whether it came from the history (it has ended).
    """
    current = _child(group, name)
    if current is not None:
        return current, False
    latest = _child(group, "Historie", name)  # the history is sorted newest first
    return latest, latest is not None


def _person_name(holder: ET.Element | None) -> str | None:
    """Name of the natural or legal person in an Inhaber/Geschaeftsfuehrer entry.

    Birth date (GebDatum) and GISA person ID are not read.
    """
    if holder is None:
        return None
    company = _text(holder, "JurPerson", "Firmenname")
    if company:
        return company
    person = _child(holder, "NatPerson")
    parts = [
        _text(person, "Titel"),
        _text(person, "Vorname"),
        _text(person, "Familienname"),
        _text(person, "NachTitel"),
    ]
    return " ".join(part for part in parts if part) or None


def _address(location: ET.Element | None) -> str | None:
    postal = _child(location, "Postadresse")
    if postal is None:
        return None
    street = " ".join(
        p
        for p in (_text(postal, "Strassenname"), _text(postal, "Orientierungsnummer"))
        if p
    )
    place = " ".join(p for p in (_text(postal, "PLZ"), _text(postal, "Ort")) if p)
    return ", ".join(p for p in (street, place) if p) or None


def _is_true(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def licence_from(element: ET.Element) -> dict[str, Any]:
    """The fields of one <Gewerbe> that the check needs (search hit or detail)."""
    right, from_history = _current_or_latest(
        _child(element, "BerechtigungDaten"), "Berechtigung"
    )
    suspension = _child(right, "Ruhend")
    owner, _ = _current_or_latest(_child(element, "InhaberDaten"), "Inhaber")
    location, _ = _current_or_latest(_child(element, "StandortDaten"), "Standort")
    # Only the current responsible person of the licence itself; those of branches,
    # tenants (Pächter) or continued operation (Fortbetrieb) are not shown.
    manager = _child(element, "GeschaeftsfuehrerDaten", "Geschaeftsfuehrer")
    return {
        "gisaNumber": _text(element, "GISAZahl"),
        "tradeKey": _text(right, "GewerbeSchluessel"),
        "trade": _text(right, "Wortlaut"),
        "authority": _text(right, "Behoerde", "Bezeichnung"),
        "start": _day(_text(right, "RechtswirksamAb")),
        "end": _day(_text(right, "EndigungDatum")),
        # True: the only entry is in the history, so the licence has ended.
        "historic": from_history,
        "suspended": _is_true(_text(suspension, "IstRuhend")),
        "suspendedFrom": _day(_text(suspension, "RuhendVon")),
        "suspendedUntil": _day(_text(suspension, "RuhendBis")),
        "location": _address(location),
        "owner": _person_name(owner),
        "manager": (
            {
                "name": _person_name(manager),
                "since": _day(_text(manager, "RechtswirksamAb")),
                "end": _day(_text(manager, "EndigungDatum")),
            }
            if manager is not None
            else None
        ),
        # Search hits have no dates; the detail call completes them.
        "detail": _child(right, "RechtswirksamAb") is not None,
    }


def _fault(root: ET.Element) -> str | None:
    for element in root.iter():
        if _name(element) == "Fault":
            text = next(
                (
                    " ".join((e.text or "").split())
                    for e in element.iter()
                    if _name(e) in ("faultstring", "Text") and (e.text or "").strip()
                ),
                None,
            )
            return text or "SOAP fault"
    return None


def _result(root: ET.Element) -> ET.Element | None:
    """The <...Result> element of the SOAP body."""
    return next((e for e in root.iter() if _name(e).endswith("Result")), None)


def _messages(result: ET.Element) -> list[dict[str, str | None]]:
    found = _child(result, "MeldungListe")
    return [
        {"code": _text(message, "Code"), "text": _text(message, "Beschreibung")}
        for message in (found if found is not None else [])
        if _name(message) == "Meldung"
    ]


def _check(root: ET.Element) -> tuple[ET.Element | None, dict[str, Any] | None]:
    """The result element, or what went wrong (fault, Returncode ERROR)."""
    fault = _fault(root)
    if fault:
        return None, {"error": SOAP_FAULT, "fault": fault}
    result = _result(root)
    if result is None:
        return None, {"error": BAD_RESPONSE, "message": "no Result in the answer"}
    if _text(result, "Returncode") == "ERROR":
        return None, {"error": GISA_ERROR, "messages": _messages(result)}
    return result, None


def parse_search(body: str) -> dict[str, Any]:
    """The company's licences from the hit list. Raises ET.ParseError if not XML."""
    result, problem = _check(ET.fromstring(body))
    if problem:
        return problem
    # Foreign insurance and credit intermediaries (VkrAuslaendische) are not licences.
    hits = _child(result, "GewerbeListe")
    return {
        "licences": [
            licence_from(e)
            for e in (hits if hits is not None else [])
            if _name(e) == "Gewerbe"
        ]
    }


def parse_detail(body: str) -> dict[str, Any]:
    """One licence in detail, or why there is none."""
    result, problem = _check(ET.fromstring(body))
    if problem:
        return problem
    licence = _child(result, "Gewerbe")
    if licence is None:
        return {"error": BAD_RESPONSE, "message": "no Gewerbe in the answer"}
    return {"licence": licence_from(licence)}


# --- what the answer means ---------------------------------------------------------------


def licence_state(licence: dict[str, Any], today: date | None = None) -> str:
    """active, suspended, ended or unknown, from the dates GISA gives."""
    day = (today or date.today()).isoformat()
    if licence.get("historic"):
        return ENDED
    end = licence.get("end")
    if end and end <= day:
        return ENDED
    if licence.get("suspended"):
        until = licence.get("suspendedUntil")
        if not until or until > day:
            return SUSPENDED
    start = licence.get("start")
    if start and start <= day:
        return ACTIVE
    # A search hit without detail, or a licence that starts in the future.
    return UNKNOWN


def licences(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """The licences with their state, for display."""
    today = _today(raw)
    found = raw.get("licences")
    if not isinstance(found, list):
        return []
    return [
        {**licence, "state": licence_state(licence, today)}
        for licence in found
        if isinstance(licence, dict)
    ]


def manager_of(
    licence: dict[str, Any], today: date | None = None
) -> dict[str, Any] | None:
    """The responsible person, unless that function has ended."""
    manager = licence.get("manager")
    if not isinstance(manager, dict):
        return None
    end = manager.get("end")
    if end and end <= (today or date.today()).isoformat():
        return None
    return manager


def check_day(raw: dict[str, Any]) -> date | None:
    """The day of the check in Vienna, as stored in the answer."""
    return _today(raw)


def _today(raw: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(raw.get("stichtag"))[:10])
    except ValueError:
        return None


class GisaAdapter(SourceAdapter):
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
        self._transport = transport

    def query(self, subject: CheckSubject, timeout: float) -> dict[str, Any]:
        number = subject.register_number
        if not number:
            # Check runs skip partners without FN before; this only guards against bugs.
            raise ValueError("GISA is searched by company register number")
        answer: dict[str, Any] = {
            "stichtag": self._now().astimezone(VIENNA).date().isoformat(),
            "checked": {"fnr": number},
        }
        if self._api_key is None:
            answer["error"] = NO_API_KEY
            return answer

        with httpx.Client(transport=self._transport) as client:
            search = self._call(
                client,
                "SearchPersonJur",
                build_search_request(self._api_key, number),
                timeout,
            )
            parsed = search["parsed"]
            if "httpStatus" in search:
                # E.g. 429 or 503: not a normal answer, whatever the body says.
                answer["httpStatus"] = search["httpStatus"]
                answer.update(parsed if "error" in parsed else {"error": BAD_RESPONSE})
                return answer
            if "error" in parsed:
                answer.update(parsed)
                return answer

            # The hit list already shows which licences have ended (only <Historie>);
            # current ones are asked in detail first, then ended ones while there is
            # room, and the list keeps GISA's order.
            found = parsed["licences"]
            asked = sorted(range(len(found)), key=lambda i: found[i]["historic"])
            asked = set(asked[:MAX_LICENCES])
            answer["licences"] = [
                self._detail(client, licence, timeout) if i in asked else licence
                for i, licence in enumerate(found)
            ]
            answer["licenceCount"] = len(found)
        return answer

    def _call(
        self, client: httpx.Client, operation: str, body: str, timeout: float
    ) -> dict[str, Any]:
        response = client.post(
            self.base_url,
            content=body.encode("utf-8"),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": f'"{SOAP_ACTION.format(operation=operation)}"',
            },
            timeout=timeout,
        )
        try:
            parsed = (
                parse_search(response.text)
                if operation == "SearchPersonJur"
                else parse_detail(response.text)
            )
        except ET.ParseError:
            parsed = {"error": BAD_RESPONSE, "message": response.text[:300]}
        if response.status_code >= 400:
            return {"httpStatus": response.status_code, "parsed": parsed}
        return {"parsed": parsed}

    def _detail(
        self, client: httpx.Client, licence: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        """The licence from the search, completed with GetGewerbeV2 if that works."""
        number = licence.get("gisaNumber")
        if not number:
            return licence
        detail = self._call(
            client,
            "GetGewerbeV2",
            build_detail_request(self._api_key or "", number),
            timeout,
        )
        found = detail["parsed"].get("licence")
        if not isinstance(found, dict):
            # Keep what the search said; the detail is missing (e.g. not found).
            return {**licence, "detailMissing": True}
        # Values from the detail win; what only the search had is kept.
        return {**licence, **{k: v for k, v in found.items() if v is not None}}

    def interpret(self, raw: dict[str, Any]) -> Interpretation:
        error = raw.get("error")
        if error == NO_API_KEY:
            return Interpretation(CheckStatus.ERROR)
        if error == GISA_ERROR:
            codes = {
                m.get("code") for m in raw.get("messages") or [] if isinstance(m, dict)
            }
            # 310 "unexpected error" may go away; a wrong key or wrong input will not.
            return Interpretation(CheckStatus.ERROR, try_again=UNEXPECTED in codes)
        http_status = raw.get("httpStatus")
        if isinstance(http_status, int) and http_status >= 400:
            temporary = http_status >= 500 or http_status == 429
            return Interpretation(CheckStatus.ERROR, try_again=temporary)
        if error or not isinstance(raw.get("licences"), list):
            return Interpretation(CheckStatus.ERROR)

        states = [licence["state"] for licence in licences(raw)]
        if ACTIVE in states:
            return Interpretation(CheckStatus.OK)
        if UNKNOWN in states:
            return Interpretation(CheckStatus.REVIEW)
        # No licence at all, or only ended and suspended ones.
        return Interpretation(CheckStatus.FINDING)

    def describe(self, status: CheckStatus, raw: dict[str, Any]) -> str:
        return describe(status, raw)

    def sample_answer(
        self, scenario: Scenario, subject: CheckSubject
    ) -> dict[str, Any]:
        stichtag = self._now().astimezone(VIENNA).date().isoformat()
        active = scenario == Scenario.OK
        return {
            "stichtag": stichtag,
            "checked": {"fnr": subject.register_number or "123456a"},
            "licenceCount": 2,
            "licences": [
                {
                    "gisaNumber": "12345678",
                    "tradeKey": "100",
                    "trade": "Baumeister (fake GISA)",
                    "authority": "Magistrat der Stadt St. Pölten",
                    "start": "2018-04-01",
                    "end": None if active else "2025-12-31",
                    "historic": not active,
                    "suspended": False,
                    "suspendedFrom": None,
                    "suspendedUntil": None,
                    "location": "Rathausplatz 6, 3100 St. Pölten",
                    "owner": "Muster Bau GmbH",
                    "manager": {
                        "name": "Ing. Maria Muster",
                        "since": "2018-04-01",
                        "end": None,
                    },
                    "detail": True,
                },
                {
                    "gisaNumber": "12345679",
                    "tradeKey": "2001",
                    "trade": "Handelsgewerbe (fake GISA)",
                    "authority": "Magistrat der Stadt St. Pölten",
                    "start": "2019-02-15",
                    "end": None,
                    "historic": False,
                    "suspended": True,
                    "suspendedFrom": "2024-01-01",
                    "suspendedUntil": None,
                    "location": "Rathausplatz 6, 3100 St. Pölten",
                    "owner": "Muster Bau GmbH",
                    "manager": None,
                    "detail": True,
                },
            ],
        }


_ERROR_MESSAGES = {
    NO_ANSWER_IN_TIME: "GISA did not answer in time.",
    NOT_REACHABLE: "GISA could not be reached.",
}


def describe(status: CheckStatus, raw: dict[str, Any]) -> str:
    """One sentence for people: what the result means and what to do."""
    number = (raw.get("checked") or {}).get("fnr")
    fn = f"FN {number}" if number else "this company register number"
    found = licences(raw)
    active = [licence for licence in found if licence["state"] == ACTIVE]

    if status == CheckStatus.OK:
        trades = "; ".join(lic.get("trade") or "licence" for lic in active)
        return (
            f"GISA lists {len(active)} active licence{'s' if len(active) != 1 else ''} "
            f"for {fn}: {trades}. Please check that they cover the planned work."
        )
    if status == CheckStatus.FINDING and not found:
        return (
            f"GISA lists no business licence for {fn}. Without a licence the partner "
            "may not carry out a regulated trade; please ask the partner."
        )
    if status == CheckStatus.FINDING:
        listed = "; ".join(
            f"{lic.get('trade') or 'licence'} ({STATE_LABELS[lic['state']]})"
            for lic in found
        )
        return (
            f"GISA lists no active licence for {fn}: {listed}. The partner may not "
            "carry out these trades at the moment; please check before ordering work."
        )
    if status == CheckStatus.REVIEW:
        return (
            f"GISA lists licences for {fn}, but their status is unclear. "
            "Please look at the licences below."
        )

    error = raw.get("error")
    if error == NO_API_KEY:
        return (
            "The GISA check is not set up on this server yet (no API key). "
            "The result was not confirmed."
        )
    if error == GISA_ERROR:
        messages = raw.get("messages") or []
        if any(m.get("code") == KEY_INVALID for m in messages if isinstance(m, dict)):
            return (
                "GISA refused our API key (not found or expired; keys expire after "
                "one year). Please ask the administrator to renew it. "
                "The result was not confirmed."
            )
        text = "; ".join(
            m.get("text") or str(m.get("code")) for m in messages if isinstance(m, dict)
        )
        detail = f": {text}" if text else ""
        return f"GISA reported an error{detail}. The result was not confirmed."
    if error == SOAP_FAULT:
        detail = f": {raw.get('fault')}" if raw.get("fault") else ""
        return f"GISA rejected the request{detail}. The result was not confirmed."
    if raw.get("httpStatus") == 429:
        return (
            "GISA is busy (too many requests). The result was not confirmed. "
            "Please try again in a minute."
        )
    reason = _ERROR_MESSAGES.get(error, "GISA could not be checked.")
    return f"{reason} The result was not confirmed. Please try again later."


def is_enabled() -> bool:
    """Check runs ask GISA when the API key is set or a fake is chosen."""
    return bool(os.environ.get("GISA_API_KEY", "").strip()) or (
        adapter_setting(SOURCE) is not None
    )


def get_gisa_adapter() -> SourceAdapter:
    """FastAPI dependency.

    GISA_API_KEY is the personal key from gisa.gv.at (secret: .env / deploy.env only).
    GISA_BASE_URL can point to another endpoint; GISA_ADAPTER=fake-... uses a fake
    without any network (see app/adapters/fake.py).
    """
    return with_fake_from_env(
        GisaAdapter(
            os.environ.get("GISA_BASE_URL") or DEFAULT_BASE_URL,
            os.environ.get("GISA_API_KEY"),
        )
    )
