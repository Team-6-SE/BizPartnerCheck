"""ÖGK HFU list (contractor liability, Auftraggeberhaftung) - S4.4.

The HFU list names the construction companies whose clients are freed from
liability for the contractor's social security contributions (§ 67a ASVG). A
partner that is NOT on the list means a withholding may apply to payments.

We ask the ÖGK web service "AGH - Webservice HFU-Abfrage extern" (SOAP 1.1,
version 3.0) live for every check:

    POST {base_url}   (document/literal, text/xml, NO SOAPAction header)

    <agh:dienstgeberAbfragen>
      <uidAuftraggeber>ATU...</uidAuftraggeber>   our organisation (the requester)
      <stichtag>2026-11-16</stichtag>             reference date: today in Vienna
      <auftragnehmerRQ><uidAuftragnehmer>ATU...</uidAuftragnehmer></auftragnehmerRQ>
    </agh:dienstgeberAbfragen>

The answer has one `auftragnehmerRS` per contractor with two flags: `hfuListeDgJN`
(on the list as employer) and `hfuListeEpuJN` (on the list as one-person company).
Either "J" -> OK, both "N" -> FINDING, anything else -> ERROR, never OK.

The requester is the organisation's own VAT number (page Settings). Without it the
service cannot be asked, and the result is ERROR with a hint. Details: docs/hfu.md
"""

import os
import xml.etree.ElementTree as ET
from datetime import UTC, date
from typing import Any
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
from app.adapters.fake import with_fake_from_env

SOURCE = "HFU"
DEFAULT_BASE_URL = (
    "https://www.sozialversicherung.at/agh-ws-prod/DienstgeberAbfrageWS_3_0"
)
# Answers fixed test data (see docs/hfu.md); for development and staging.
TEST_BASE_URL = "https://www.sozialversicherung.at/agh-ws-tt/DienstgeberAbfrageWS_3_0"

NAMESPACE = "http://AGHExternWS_3_0.extern_3_0.ws.agh.noegkk.sozvers.at/"
SOAP_ENVELOPE = "http://schemas.xmlsoap.org/soap/envelope/"

# Our own error codes for this source.
NO_REQUESTER = "NO_REQUESTER"  # the organisation's own VAT number is not set
SOAP_FAULT = "SOAP_FAULT"  # the service refused the request (e.g. bad input)

YES = "J"
NO = "N"

# The list is Austrian, so "today" is the day in Vienna, not in UTC.
try:
    VIENNA: Any = ZoneInfo("Europe/Vienna")
except ZoneInfoNotFoundError:  # pragma: no cover - no time zone database
    VIENNA = UTC

RESULT_FIELDS = (
    "dgnrAuftragnehmer",
    "vsnrAuftragnehmer",
    "auftragnehmerName",
    "auftragnehmerHauptanschrift",
    "firmenbuchnummer",
    "uid",
    "hfuListeDgJN",
    "hfuListeEpuJN",
    "hinweis",
)


def build_request(requester_vat: str, vat_number: str, stichtag: date) -> str:
    """The SOAP body: our UID as requester, the partner's UID as contractor."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<soapenv:Envelope xmlns:soapenv="{SOAP_ENVELOPE}" xmlns:agh="{NAMESPACE}">'
        "<soapenv:Header/><soapenv:Body><agh:dienstgeberAbfragen>"
        f"<uidAuftraggeber>{escape(requester_vat)}</uidAuftraggeber>"
        f"<stichtag>{stichtag.isoformat()}</stichtag>"
        "<auftragnehmerRQ>"
        f"<uidAuftragnehmer>{escape(vat_number)}</uidAuftragnehmer>"
        "</auftragnehmerRQ>"
        "</agh:dienstgeberAbfragen></soapenv:Body></soapenv:Envelope>"
    )


def _local(tag: str) -> str:
    """'{namespace}name' -> 'name'; the service mixes prefixes freely."""
    return tag.rsplit("}", 1)[-1]


def _text(element: ET.Element, name: str) -> str | None:
    for child in element:
        if _local(child.tag) == name:
            text = (child.text or "").strip()
            return text or None
    return None


def _result(element: ET.Element) -> dict[str, Any]:
    """One auftragnehmerRS as a dict with the service's own field names."""
    result: dict[str, Any] = {name: _text(element, name) for name in RESULT_FIELDS}
    result["einzelunternehmen"] = [
        {
            "name": _text(child, "name"),
            "firmenbuchnummer": _text(child, "firmenbuchnummer"),
        }
        for child in element
        if _local(child.tag) == "einzelunternehmen"
    ]
    return result


def parse_response(body: str) -> dict[str, Any]:
    """The SOAP answer as a dict: the results, or what the service complained about.

    Raises ET.ParseError when the body is not XML.
    """
    root = ET.fromstring(body)
    for element in root.iter():
        if _local(element.tag) == "Fault":
            return {
                "error": SOAP_FAULT,
                "faultcode": _text(element, "faultcode"),
                "faultstring": _text(element, "faultstring"),
            }
    if not any(_local(e.tag) == "dienstgeberAbfragenResponse" for e in root.iter()):
        return {"error": BAD_RESPONSE, "message": "no dienstgeberAbfragenResponse"}
    return {
        "auftragnehmerRS": [
            _result(e) for e in root.iter() if _local(e.tag) == "auftragnehmerRS"
        ]
    }


class HfuAdapter(SourceAdapter):
    source = SOURCE

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        transport: httpx.BaseTransport | None = None,
        **options: Any,
    ) -> None:
        super().__init__(**options)
        self.base_url = base_url
        # Tests pass a fake transport, so they never need the internet.
        self._transport = transport

    def stichtag(self) -> date:
        """The reference date of the check: today in Vienna."""
        return self._now().astimezone(VIENNA).date()

    def answer_without_requester(self, subject: CheckSubject) -> dict[str, Any]:
        """The raw answer when the organisation's own VAT number is not set."""
        return {
            **self._base(subject),
            "error": NO_REQUESTER,
            "message": "The organisation's own VAT number is not set.",
        }

    def _base(self, subject: CheckSubject) -> dict[str, Any]:
        return {
            "stichtag": self.stichtag().isoformat(),
            "requester": {"uidAuftraggeber": subject.requester_vat},
            "checked": {"uidAuftragnehmer": subject.vat_number},
        }

    def query(self, subject: CheckSubject, timeout: float) -> dict[str, Any]:
        """Ask the ÖGK service once about the partner's VAT number."""
        vat_number = subject.vat_number
        if not vat_number:
            # The API refuses such partners before; this only guards against bugs.
            raise ValueError("HFU needs a VAT number")
        if not subject.requester_vat:
            return self.answer_without_requester(subject)

        body = build_request(subject.requester_vat, vat_number, self.stichtag())
        with httpx.Client(transport=self._transport) as client:
            # No SOAPAction header: the service rejects requests that carry one.
            response = client.post(
                self.base_url,
                content=body.encode("utf-8"),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "Accept": "text/xml",
                },
                timeout=timeout,
            )

        try:
            parsed = parse_response(response.text)
        except ET.ParseError:
            parsed = {"error": BAD_RESPONSE, "message": response.text[:500]}

        answer = {**self._base(subject), **parsed}
        if response.status_code >= 400 or "error" in parsed:
            # httpStatus marks an answer that was not a normal result.
            answer["httpStatus"] = response.status_code
        return answer

    def interpret(self, raw: dict[str, Any]) -> Interpretation:
        error = raw.get("error")
        if error in (NO_REQUESTER, SOAP_FAULT):
            # A setting or our input: the same request would fail again.
            return Interpretation(CheckStatus.ERROR)
        http_status = raw.get("httpStatus")
        if isinstance(http_status, int) and http_status >= 400:
            # 5xx and 429 may go away; other HTTP errors will not change when asked again.
            temporary = http_status >= 500 or http_status == 429
            return Interpretation(CheckStatus.ERROR, try_again=temporary)
        if error:
            return Interpretation(CheckStatus.ERROR)

        first = first_result(raw)
        if first is None:
            return Interpretation(CheckStatus.ERROR)
        employer, sole_trader = first.get("hfuListeDgJN"), first.get("hfuListeEpuJN")
        if YES in (employer, sole_trader):
            return Interpretation(CheckStatus.OK)
        if employer == NO and sole_trader == NO:
            return Interpretation(CheckStatus.FINDING)
        return Interpretation(CheckStatus.ERROR)

    def describe(self, status: CheckStatus, raw: dict[str, Any]) -> str:
        return describe(status, raw)

    def sample_answer(
        self, scenario: Scenario, subject: CheckSubject
    ) -> dict[str, Any]:
        listed = scenario == Scenario.OK
        return {
            **self._base(subject),
            "auftragnehmerRS": [
                {
                    "dgnrAuftragnehmer": "999999999",
                    "vsnrAuftragnehmer": None,
                    "auftragnehmerName": "Muster Bau GmbH (fake HFU)",
                    "auftragnehmerHauptanschrift": "3100 St. Pölten, Rathausplatz 6",
                    "firmenbuchnummer": "123456d",
                    "uid": subject.vat_number,
                    "hfuListeDgJN": YES if listed else NO,
                    "hfuListeEpuJN": NO,
                    "hinweis": None,
                    "einzelunternehmen": [],
                }
            ],
        }


def first_result(raw: dict[str, Any]) -> dict[str, Any] | None:
    """The entry for the partner we asked about (we ask about one at a time)."""
    results = raw.get("auftragnehmerRS")
    if isinstance(results, list) and results and isinstance(results[0], dict):
        return results[0]
    return None


def error_code(raw: dict[str, Any]) -> str | None:
    value = raw.get("error")
    return value if isinstance(value, str) else None


def company_name(raw: dict[str, Any]) -> str | None:
    first = first_result(raw) or {}
    name = first.get("auftragnehmerName")
    return name if isinstance(name, str) and name.strip() else None


def _day(value: Any) -> str | None:
    """'2026-11-16' -> '16 Nov 2026'."""
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError:
        return None
    return f"{parsed.day} {parsed:%b %Y}"


def describe(status: CheckStatus, raw: dict[str, Any]) -> str:
    """One sentence for people: what the result means and what to do."""
    first = first_result(raw) or {}
    day = _day(raw.get("stichtag"))
    as_of = f" as of {day}" if day else ""
    name = company_name(raw)
    who = f" ({name})" if name else ""
    note = first.get("hinweis")
    note_text = f" Note from the ÖGK: {note}" if isinstance(note, str) and note else ""

    if status == CheckStatus.OK:
        how = (
            "as employer"
            if first.get("hfuListeDgJN") == YES
            else "as one-person company (EPU)"
        )
        return (
            f"This partner{who} is on the HFU list{as_of} {how}: no withholding for "
            "contractor liability (Auftraggeberhaftung) is needed on payments."
            f"{note_text}"
        )
    if status == CheckStatus.FINDING:
        return (
            f"This partner{who} is not on the HFU list{as_of}. A withholding may "
            "apply to payments: for construction work, the client may have to pay "
            "part of the invoice amount to the Dienstleistungszentrum instead of the "
            "partner (Auftraggeberhaftung). Not being listed is not proof of a "
            f"problem, e.g. young firms cannot be on the list yet.{note_text}"
        )

    code = error_code(raw)
    if code == NO_REQUESTER:
        return (
            "The HFU list could not be checked: your organisation's own VAT number "
            "is not set. Please set it in the organisation settings. "
            "The result was not confirmed."
        )
    if code == SOAP_FAULT:
        reason = raw.get("faultstring")
        detail = f": {reason}" if isinstance(reason, str) and reason else ""
        return (
            f"The ÖGK HFU service rejected the request{detail}. "
            "The result was not confirmed."
        )
    reasons = {
        NO_ANSWER_IN_TIME: "The ÖGK HFU service did not answer in time.",
        NOT_REACHABLE: "The ÖGK HFU service could not be reached.",
    }
    reason = reasons.get(code or "", "The HFU list could not be checked.")
    return f"{reason} The result was not confirmed. Please try again later."


def get_hfu_adapter() -> SourceAdapter:
    """FastAPI dependency.

    HFU_BASE_URL can point to the ÖGK test system or a stub; HFU_ADAPTER=fake-...
    uses a fake without any network (see app/adapters/fake.py).
    """
    return with_fake_from_env(
        HfuAdapter(os.environ.get("HFU_BASE_URL") or DEFAULT_BASE_URL)
    )
