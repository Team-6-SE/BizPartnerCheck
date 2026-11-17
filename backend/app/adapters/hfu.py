"""ÖGK HFU list: is the partner a "haftungsfreistellendes Unternehmen"? (S4.4)

If a construction partner is on the HFU list, the client is freed from liability
for its social security contributions. If not, a withholding may apply to payments.

We ask the ÖGK SOAP service "HFU-Abfrage extern" (version 3.0) for every check:

    POST {base_url}   (text/xml, no SOAPAction header - the server rejects it)

    <agh:dienstgeberAbfragen>
      <uidAuftraggeber>ATU...</uidAuftraggeber>     our organisation's VAT number
      <stichtag>2026-11-16</stichtag>               reference date: today in Vienna
      <auftragnehmerRQ><uidAuftragnehmer>ATU...</uidAuftragnehmer></auftragnehmerRQ>
    </agh:dienstgeberAbfragen>

The answer has one `auftragnehmerRS` per partner with the flags `hfuListeDgJN`
(listed as employer) and `hfuListeEpuJN` (listed as one-person company): either
"J" -> OK, both "N" -> FINDING, anything else -> ERROR. Details: docs/hfu.md
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
from app.adapters.fake import with_fake_from_env

SOURCE = "HFU"
DEFAULT_BASE_URL = (
    "https://www.sozialversicherung.at/agh-ws-prod/DienstgeberAbfrageWS_3_0"
)
NAMESPACE = "http://AGHExternWS_3_0.extern_3_0.ws.agh.noegkk.sozvers.at/"

# Our own error codes for this source.
NO_REQUESTER = "NO_REQUESTER"  # the organisation's own VAT number is not set
SOAP_FAULT = "SOAP_FAULT"  # the service refused the request

# The list is Austrian, so "today" is the day in Vienna.
VIENNA = ZoneInfo("Europe/Vienna")

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
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:agh="{NAMESPACE}">'
        "<soapenv:Header/><soapenv:Body><agh:dienstgeberAbfragen>"
        f"<uidAuftraggeber>{escape(requester_vat)}</uidAuftraggeber>"
        f"<stichtag>{stichtag.isoformat()}</stichtag>"
        "<auftragnehmerRQ>"
        f"<uidAuftragnehmer>{escape(vat_number)}</uidAuftragnehmer>"
        "</auftragnehmerRQ>"
        "</agh:dienstgeberAbfragen></soapenv:Body></soapenv:Envelope>"
    )


def _name(element: ET.Element) -> str:
    # "{namespace}tag" -> "tag": the service mixes prefixes, so we ignore them.
    return element.tag.rsplit("}", 1)[-1]


def _text(element: ET.Element, name: str) -> str | None:
    for child in element:
        if _name(child) == name:
            return (child.text or "").strip() or None
    return None


def parse_response(body: str) -> dict[str, Any]:
    """The SOAP answer as a dict. Raises ET.ParseError if it is not XML."""
    root = ET.fromstring(body)
    elements = list(root.iter())
    for element in elements:
        if _name(element) == "Fault":
            return {
                "error": SOAP_FAULT,
                "faultcode": _text(element, "faultcode"),
                "faultstring": _text(element, "faultstring"),
            }
    if not any(_name(e) == "dienstgeberAbfragenResponse" for e in elements):
        return {"error": BAD_RESPONSE, "message": "no dienstgeberAbfragenResponse"}

    results = []
    for element in elements:
        if _name(element) != "auftragnehmerRS":
            continue
        result: dict[str, Any] = {f: _text(element, f) for f in RESULT_FIELDS}
        result["einzelunternehmen"] = [
            {"name": _text(c, "name"), "firmenbuchnummer": _text(c, "firmenbuchnummer")}
            for c in element
            if _name(c) == "einzelunternehmen"
        ]
        results.append(result)
    return {"auftragnehmerRS": results}


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

    def query(self, subject: CheckSubject, timeout: float) -> dict[str, Any]:
        vat_number = subject.vat_number
        if not vat_number:
            # The API refuses such partners before; this only guards against bugs.
            raise ValueError("HFU needs a VAT number")

        stichtag = self._now().astimezone(VIENNA).date()
        answer: dict[str, Any] = {
            "stichtag": stichtag.isoformat(),
            "requester": {"uidAuftraggeber": subject.requester_vat},
            "checked": {"uidAuftragnehmer": vat_number},
        }
        if not subject.requester_vat:
            # The service needs to know who asks; without our VAT number we cannot ask.
            answer["error"] = NO_REQUESTER
            return answer

        body = build_request(subject.requester_vat, vat_number, stichtag)
        with httpx.Client(transport=self._transport) as client:
            response = client.post(
                self.base_url,
                content=body.encode("utf-8"),
                headers={"Content-Type": "text/xml; charset=utf-8"},
                timeout=timeout,
            )
        try:
            parsed = parse_response(response.text)
        except ET.ParseError:
            parsed = {"error": BAD_RESPONSE, "message": response.text[:500]}

        answer.update(parsed)
        if response.status_code >= 400 or "error" in parsed:
            # httpStatus marks an answer that was not a normal result.
            answer["httpStatus"] = response.status_code
        return answer

    def interpret(self, raw: dict[str, Any]) -> Interpretation:
        error = raw.get("error")
        if error in (NO_REQUESTER, SOAP_FAULT):
            # Our setting or our input is wrong: asking again would not help.
            return Interpretation(CheckStatus.ERROR)
        http_status = raw.get("httpStatus")
        if isinstance(http_status, int) and http_status >= 400:
            # 5xx and 429 may go away; other HTTP errors will not change when asked again.
            temporary = http_status >= 500 or http_status == 429
            return Interpretation(CheckStatus.ERROR, try_again=temporary)
        if error:
            return Interpretation(CheckStatus.ERROR)

        result = _result(raw)
        flags = (result.get("hfuListeDgJN"), result.get("hfuListeEpuJN"))
        if "J" in flags:
            return Interpretation(CheckStatus.OK)
        if flags == ("N", "N"):
            return Interpretation(CheckStatus.FINDING)
        return Interpretation(CheckStatus.ERROR)

    def describe(self, status: CheckStatus, raw: dict[str, Any]) -> str:
        return describe(status, raw)

    def sample_answer(
        self, scenario: Scenario, subject: CheckSubject
    ) -> dict[str, Any]:
        return {
            "stichtag": self._now().astimezone(VIENNA).date().isoformat(),
            "requester": {"uidAuftraggeber": subject.requester_vat},
            "checked": {"uidAuftragnehmer": subject.vat_number},
            "auftragnehmerRS": [
                {
                    "dgnrAuftragnehmer": "999999999",
                    "vsnrAuftragnehmer": None,
                    "auftragnehmerName": "Muster Bau GmbH (fake HFU)",
                    "auftragnehmerHauptanschrift": "3100 St. Pölten, Rathausplatz 6",
                    "firmenbuchnummer": "123456d",
                    "uid": subject.vat_number,
                    "hfuListeDgJN": "J" if scenario == Scenario.OK else "N",
                    "hfuListeEpuJN": "N",
                    "hinweis": None,
                    "einzelunternehmen": [],
                }
            ],
        }


def _result(raw: dict[str, Any]) -> dict[str, Any]:
    """The entry for the partner we asked about (we always ask about one)."""
    results = raw.get("auftragnehmerRS")
    if isinstance(results, list) and results and isinstance(results[0], dict):
        return results[0]
    return {}


def _day(value: Any) -> str:
    """'2026-11-16' -> ' as of 16 Nov 2026', or '' if unknown."""
    try:
        parsed = date.fromisoformat(str(value)[:10])
    except ValueError:
        return ""
    return f" as of {parsed.day} {parsed:%b %Y}"


_ERROR_MESSAGES = {
    NO_ANSWER_IN_TIME: "The ÖGK HFU service did not answer in time.",
    NOT_REACHABLE: "The ÖGK HFU service could not be reached.",
}


def describe(status: CheckStatus, raw: dict[str, Any]) -> str:
    """One sentence for people: what the result means and what to do."""
    result = _result(raw)
    as_of = _day(raw.get("stichtag"))
    name = result.get("auftragnehmerName")
    who = f" ({name})" if name else ""
    note = result.get("hinweis")
    note_text = f" Note from the ÖGK: {note}" if note else ""

    if status == CheckStatus.OK:
        how = (
            "as employer"
            if result.get("hfuListeDgJN") == "J"
            else "as one-person company (EPU)"
        )
        return (
            f"This partner{who} is on the HFU list{as_of} {how}: no withholding for "
            f"contractor liability (Auftraggeberhaftung) is needed on payments.{note_text}"
        )
    if status == CheckStatus.FINDING:
        return (
            f"This partner{who} is not on the HFU list{as_of}. A withholding may "
            "apply to payments: for construction work, the client may have to pay "
            "part of the invoice amount to the Dienstleistungszentrum instead of the "
            "partner (Auftraggeberhaftung). Not being listed is not proof of a "
            f"problem, e.g. young firms cannot be on the list yet.{note_text}"
        )

    error = raw.get("error")
    if error == NO_REQUESTER:
        return (
            "The HFU list could not be checked: your organisation's own VAT number "
            "is not set. Please set it in the organisation settings. "
            "The result was not confirmed."
        )
    if error == SOAP_FAULT:
        reason = raw.get("faultstring")
        detail = f": {reason}" if reason else ""
        return (
            f"The ÖGK HFU service rejected the request{detail}. "
            "The result was not confirmed."
        )
    reason = _ERROR_MESSAGES.get(error, "The HFU list could not be checked.")
    return f"{reason} The result was not confirmed. Please try again later."


def get_hfu_adapter() -> SourceAdapter:
    """FastAPI dependency.

    HFU_BASE_URL can point to the ÖGK test system; HFU_ADAPTER=fake-... uses a
    fake without any network (see app/adapters/fake.py).
    """
    return with_fake_from_env(
        HfuAdapter(os.environ.get("HFU_BASE_URL") or DEFAULT_BASE_URL)
    )
