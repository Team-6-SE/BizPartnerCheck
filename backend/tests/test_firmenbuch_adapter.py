"""The Firmenbuch adapter with fake SOAP answers: no internet and no API key needed.

The answers follow the examples and the XSD (auszugResponse_v2.xsd) of the
"FBW-WebServices (HVD) Schnittstellenbeschreibung" v1.3, with the service's own
namespace prefixes (ns6) on elements and attributes.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime

import httpx2 as httpx
import pytest

from app.adapters.base import CheckStatus, CheckSubject, Scenario
from app.adapters.fake import FakeAdapter
from app.adapters.firmenbuch import (
    API_KEY_HEADER,
    NO_API_KEY,
    SOAP_FAULT,
    FirmenbuchAdapter,
    address_text,
    describe,
    is_enabled,
    parse_response,
    status_flags,
)
from app.adapters.limits import Limits

BASE_URL = "https://firmenbuch.test/jop/api/at.gv.justiz.fbw/ws"
API_KEY = "secret-test-token"
FN = "58468h"
# 23:30 UTC is already the next day in Vienna: the reference date must follow Vienna.
NOW = datetime(2026, 11, 18, 23, 30, tzinfo=UTC)
TODAY_IN_VIENNA = "2026-11-19"
NS = "ns://firmenbuch.justiz.gv.at/Abfrage/v2/AuszugResponse"

SUBJECT = CheckSubject(vat_number=None, register_number=FN)

DIRECTOR = """
<ns6:FUN ns6:PNR="  A" ns6:FKEN="GF" ns6:FKENTEXT="GESCHÄFTSFÜHRER/IN (handelsrechtlich)">
  <ns6:FU_DKZ10 ns6:AUFRECHT="true" ns6:VNR="012">
    <ns6:DATVON>2015-03-01</ns6:DATVON>
    <ns6:VART><ns6:CODE>SE</ns6:CODE><ns6:TEXT>vertritt seit 01.03.2015 selbständig</ns6:TEXT></ns6:VART>
  </ns6:FU_DKZ10>
</ns6:FUN>
<ns6:FUN ns6:PNR="  B" ns6:FKEN="GS" ns6:FKENTEXT="GESELLSCHAFTER/IN">
  <ns6:FU_DKZ10 ns6:AUFRECHT="true" ns6:VNR="001">
    <ns6:DATVON>2001-06-12</ns6:DATVON>
    <ns6:KAPITAL>35000</ns6:KAPITAL>
  </ns6:FU_DKZ10>
</ns6:FUN>
<ns6:FUN ns6:PNR="  C" ns6:FKEN="GF" ns6:FKENTEXT="GESCHÄFTSFÜHRER/IN (handelsrechtlich)">
  <ns6:FU_DKZ10 ns6:AUFRECHT="false" ns6:VNR="001">
    <ns6:DATVON>2001-06-12</ns6:DATVON>
    <ns6:DATBIS>2015-02-28</ns6:DATBIS>
  </ns6:FU_DKZ10>
</ns6:FUN>
<ns6:PER ns6:PNR="  A">
  <ns6:PE_DKZ02 ns6:AUFRECHT="true" ns6:VNR="012">
    <ns6:TITELVOR>Dipl.-Ing.</ns6:TITELVOR>
    <ns6:VORNAME>Maria</ns6:VORNAME>
    <ns6:NACHNAME>Went</ns6:NACHNAME>
    <ns6:GEBURTSDATUM>1970-05-17</ns6:GEBURTSDATUM>
  </ns6:PE_DKZ02>
  <ns6:PE_DKZ03 ns6:AUFRECHT="true" ns6:VNR="012">
    <ns6:STELLE>Privatgasse 9</ns6:STELLE><ns6:PLZ>8010</ns6:PLZ><ns6:ORT>Graz</ns6:ORT>
  </ns6:PE_DKZ03>
  <ns6:PE_STAAT><ns6:STAATSBUERGERSCHAFT>AUT</ns6:STAATSBUERGERSCHAFT>
    <ns6:WOHNSITZSTAAT>AUT</ns6:WOHNSITZSTAAT></ns6:PE_STAAT>
</ns6:PER>
<ns6:PER ns6:PNR="  B">
  <ns6:PE_DKZ02 ns6:AUFRECHT="true" ns6:VNR="001">
    <ns6:BEZEICHNUNG>Went Holding</ns6:BEZEICHNUNG>
    <ns6:BEZEICHNUNG>GmbH</ns6:BEZEICHNUNG>
  </ns6:PE_DKZ02>
</ns6:PER>
<ns6:PER ns6:PNR="  C">
  <ns6:PE_DKZ02 ns6:AUFRECHT="true" ns6:VNR="001">
    <ns6:VORNAME>Karl</ns6:VORNAME><ns6:NACHNAME>Alt</ns6:NACHNAME>
  </ns6:PE_DKZ02>
</ns6:PER>
"""


def legal_fact(text: str, aufrecht: str = "true") -> str:
    return (
        f'<ns6:RECHTSTATSACHE ns6:UNR="001"><ns6:RTS_DKZ50 ns6:AUFRECHT="{aufrecht}" '
        f'ns6:VNR="040"><ns6:CODE>99</ns6:CODE><ns6:DATUM_VOM>2026-10-01</ns6:DATUM_VOM>'
        f"<ns6:TEXT>{text}</ns6:TEXT></ns6:RTS_DKZ50></ns6:RECHTSTATSACHE>"
    )


def extract(
    *,
    name: tuple[str, ...] = ("EDV-Technik Dipl.-Ing. Went", "Gesellschaft m.b.H."),
    facts: str = "",
    deleted: str = "",
    functions: str = DIRECTOR,
) -> str:
    """Like the sample response in the interface description, plus the XSD parts."""
    deleted_attr = f' ns6:MIT_FIRMA_GELOESCHT_DURCH_VNR="{deleted}"' if deleted else ""
    lines = "".join(f"<ns6:BEZEICHNUNG>{line}</ns6:BEZEICHNUNG>" for line in name)
    return f"""<env:Envelope xmlns:env="http://www.w3.org/2003/05/soap-envelope">
<env:Header/><env:Body>
<ns6:AUSZUG_V2_RESPONSE ns6:ABFRAGEZEITPUNKT="2026-11-19T00:30:00.146+01:00"
  ns6:FNR="58468 h" ns6:PRUEFSUMME="452407D2F7C4C4A3ED83D51DFB961E82"
  ns6:STICHTAG="{TODAY_IN_VIENNA}" ns6:UMFANG="Kurzinformation" xmlns:ns6="{NS}">
  <ns6:FIRMA>
    <ns6:FI_DKZ02 ns6:AUFRECHT="false" ns6:VNR="001"><ns6:BEZEICHNUNG>Old Name GmbH</ns6:BEZEICHNUNG></ns6:FI_DKZ02>
    <ns6:FI_DKZ02 ns6:AUFRECHT="true" ns6:VNR="002"{deleted_attr}>{lines}</ns6:FI_DKZ02>
    <ns6:FI_DKZ03 ns6:AUFRECHT="true" ns6:VNR="034">
      <ns6:STELLE>Kärntner Straße 337</ns6:STELLE><ns6:STAAT>AUT</ns6:STAAT>
      <ns6:PLZ>8054</ns6:PLZ><ns6:ORT>Graz</ns6:ORT><ns6:ZUSTELLBAR>true</ns6:ZUSTELLBAR>
    </ns6:FI_DKZ03>
    <ns6:FI_DKZ06 ns6:AUFRECHT="true" ns6:VNR="001">
      <ns6:ORTNR><ns6:CODE>60101</ns6:CODE><ns6:TEXT>Graz</ns6:TEXT></ns6:ORTNR>
      <ns6:SITZ>Graz</ns6:SITZ>
    </ns6:FI_DKZ06>
    <ns6:FI_DKZ07 ns6:AUFRECHT="true" ns6:VNR="001">
      <ns6:RECHTSFORM><ns6:CODE>GES</ns6:CODE>
      <ns6:TEXT>Gesellschaft mit beschränkter Haftung</ns6:TEXT></ns6:RECHTSFORM>
    </ns6:FI_DKZ07>
    {facts}
  </ns6:FIRMA>
  {functions}
  <ns6:VOLLZ><ns6:VNR>001</ns6:VNR><ns6:VOLLZUGSDATUM>2001-06-12</ns6:VOLLZUGSDATUM>
    <ns6:HG><ns6:CODE>630</ns6:CODE><ns6:TEXT>Landesgericht für ZRS Graz</ns6:TEXT></ns6:HG>
    <ns6:AZ>039 Fr 1/01 a</ns6:AZ><ns6:ANTRAGSTEXT>Neueintragung</ns6:ANTRAGSTEXT></ns6:VOLLZ>
</ns6:AUSZUG_V2_RESPONSE>
</env:Body></env:Envelope>"""


def fault(text: str) -> str:
    """Like the SOAP fault example in the interface description."""
    return (
        '<env:Envelope xmlns:env="http://www.w3.org/2003/05/soap-envelope">'
        "<env:Header/><env:Body><env:Fault><env:Code><env:Value>env:Receiver"
        "</env:Value></env:Code><env:Reason>"
        f'<env:Text xml:lang="en">{text}</env:Text>'
        "</env:Reason></env:Fault></env:Body></env:Envelope>"
    )


Handler = Callable[[httpx.Request], httpx.Response]


def make_adapter(
    handler: Handler, api_key: str | None = API_KEY, **options
) -> tuple[FirmenbuchAdapter, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    options.setdefault("limits", Limits())  # defaults, whatever the environment says
    adapter = FirmenbuchAdapter(
        BASE_URL,
        api_key,
        transport=httpx.MockTransport(record),
        sleep=lambda _seconds: None,
        now=lambda: NOW,
        **options,
    )
    return adapter, requests


def answers(*items: str | Exception, status: int = 200) -> Handler:
    queue = list(items)

    def handler(_request: httpx.Request) -> httpx.Response:
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return httpx.Response(status, text=item)

    return handler


# --- the request ----------------------------------------------------------------------


def test_request_follows_the_interface_description() -> None:
    adapter, requests = make_adapter(answers(extract()))

    adapter.check(SUBJECT)

    request = requests[0]
    assert str(request.url) == BASE_URL
    assert request.headers[API_KEY_HEADER] == API_KEY
    assert request.headers["Content-Type"] == "application/soap+xml;charset=UTF-8"
    body = request.content.decode()
    assert "http://www.w3.org/2003/05/soap-envelope" in body  # SOAP 1.2
    assert "<aus:FNR>58468h</aus:FNR>" in body
    assert f"<aus:STICHTAG>{TODAY_IN_VIENNA}</aus:STICHTAG>" in body
    assert "<aus:UMFANG>Kurzinformation</aus:UMFANG>" in body


def test_without_api_key_nothing_is_sent_and_the_result_is_error() -> None:
    adapter, requests = make_adapter(answers(extract()), api_key="  ")

    result = adapter.check(SUBJECT)

    assert requests == []
    assert result.status == CheckStatus.ERROR
    assert result.raw["error"] == NO_API_KEY
    assert "not set up on this server yet" in result.explanation


def test_the_api_key_is_never_stored() -> None:
    adapter, _ = make_adapter(answers(extract()))

    result = adapter.check(SUBJECT)

    assert API_KEY not in json.dumps(result.raw)


# --- registered and active --------------------------------------------------------------


def test_registered_company_is_ok_with_name_seat_legal_form_and_number() -> None:
    adapter, _ = make_adapter(answers(extract()))

    result = adapter.check(SUBJECT)

    assert result.status == CheckStatus.OK
    company = result.raw["company"]
    # The current name, not the one that was replaced (AUFRECHT="false").
    assert company["name"] == "EDV-Technik Dipl.-Ing. Went Gesellschaft m.b.H."
    assert company["seat"] == "Graz"
    assert company["legalForm"]["text"] == "Gesellschaft mit beschränkter Haftung"
    assert result.raw["register"]["fnr"] == "58468 h"
    assert address_text(result.raw) == "Kärntner Straße 337\n8054 Graz"
    assert result.explanation == (
        "EDV-Technik Dipl.-Ing. Went Gesellschaft m.b.H. is registered in the "
        "Firmenbuch under FN 58468 h as of 19 Nov 2026 (Gesellschaft mit beschränkter "
        "Haftung, seat Graz). No deletion, insolvency or liquidation is recorded."
    )
    assert result.data_as_of is None  # live source


def test_only_current_persons_with_name_role_and_start_date() -> None:
    adapter, _ = make_adapter(answers(extract()))

    result = adapter.check(SUBJECT)

    assert result.raw["persons"] == [
        {
            "name": "Dipl.-Ing. Maria Went",
            "role": "GESCHÄFTSFÜHRER/IN (handelsrechtlich)",
            "roleCode": "GF",
            "since": "2015-03-01",
        },
        {
            "name": "Went Holding GmbH",
            "role": "GESELLSCHAFTER/IN",
            "roleCode": "GS",
            "since": "2001-06-12",
        },
    ]


def test_birth_dates_private_addresses_and_citizenship_are_not_kept() -> None:
    adapter, _ = make_adapter(answers(extract()))

    stored = json.dumps(adapter.check(SUBJECT).raw, ensure_ascii=False)

    assert "1970-05-17" not in stored
    assert "Privatgasse" not in stored
    assert "STAATSBUERGERSCHAFT" not in stored and "WOHNSITZ" not in stored
    assert "35000" not in stored  # capital shares are not needed either


def test_whole_name_in_last_name_is_not_doubled() -> None:
    person = """<ns6:FUN ns6:PNR="A" ns6:FKEN="GF" ns6:FKENTEXT="GF"/>
    <ns6:PER ns6:PNR="A"><ns6:PE_DKZ02 ns6:AUFRECHT="true">
      <ns6:VORNAME>Maria</ns6:VORNAME><ns6:NACHNAME>Dr. Maria Went</ns6:NACHNAME>
    </ns6:PE_DKZ02></ns6:PER>"""

    raw = parse_response(extract(functions=person))

    assert raw["persons"][0]["name"] == "Dr. Maria Went"
    assert raw["persons"][0]["since"] is None


# --- status flags -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Konkurs eröffnet", "insolvency"),
        ("Sanierungsverfahren ohne Eigenverwaltung eröffnet", "insolvency"),
        ("Die Gesellschaft ist aufgelöst.", "liquidation"),
        ("Amtswegige Löschung gemäß § 40 FBG", "deleted"),
    ],
)
def test_insolvency_liquidation_and_deletion_are_findings_with_the_flag(
    text: str, kind: str
) -> None:
    adapter, _ = make_adapter(answers(extract(facts=legal_fact(text))))

    result = adapter.check(SUBJECT)

    assert result.status == CheckStatus.FINDING
    assert [flag["kind"] for flag in status_flags(result.raw)] == [kind]
    assert text in result.explanation
    assert "Please check carefully" in result.explanation


def test_company_deleted_with_an_entry_is_a_finding() -> None:
    adapter, _ = make_adapter(answers(extract(deleted="045")))

    result = adapter.check(SUBJECT)

    assert result.status == CheckStatus.FINDING
    assert "deleted from the register" in result.explanation


def test_in_liquidation_in_the_name_is_a_finding() -> None:
    raw = parse_response(extract(name=("Went GmbH in Liqu.",)))

    adapter, _ = make_adapter(answers(extract(name=("Went GmbH in Liqu.",))))

    assert [flag["kind"] for flag in status_flags(raw)] == ["liquidation"]
    assert adapter.check(SUBJECT).status == CheckStatus.FINDING


def test_legal_facts_that_are_no_longer_valid_are_ignored() -> None:
    adapter, _ = make_adapter(
        answers(extract(facts=legal_fact("Konkurs eröffnet", aufrecht="false")))
    )

    assert adapter.check(SUBJECT).status == CheckStatus.OK


def test_ended_insolvency_proceedings_need_a_review() -> None:
    adapter, _ = make_adapter(
        answers(extract(facts=legal_fact("Sanierungsverfahren aufgehoben")))
    )

    result = adapter.check(SUBJECT)

    assert result.status == CheckStatus.REVIEW
    assert "ended proceedings" in result.explanation
    assert "Sanierungsverfahren aufgehoben" in result.explanation


# --- not found and errors: shown differently --------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Die Firmenbuchnummer 999999z wurde nicht gefunden",
        'Der Parameter "FNR" ist ungültig',
        "Firma existiert nicht",
    ],
)
def test_unknown_register_number_is_a_finding_not_an_error(text: str) -> None:
    # SOAP faults come with HTTP 500: "not found" must still win over the status.
    adapter, requests = make_adapter(answers(fault(text), status=500))

    result = adapter.check(SUBJECT)

    assert result.status == CheckStatus.FINDING
    assert result.raw["notFound"] is True
    assert len(requests) == 1  # not asked again
    assert "has no company with FN 58468h" in result.explanation


def test_other_soap_faults_are_errors_and_not_retried() -> None:
    adapter, requests = make_adapter(
        answers(fault("Stichtag darf nicht in der Zukunft sein"), status=500)
    )

    result = adapter.check(SUBJECT)

    assert result.status == CheckStatus.ERROR
    assert result.raw["error"] == SOAP_FAULT
    assert len(requests) == 1
    assert "Stichtag darf nicht in der Zukunft sein" in result.explanation


def test_too_many_requests_is_retried_then_error() -> None:
    adapter, requests = make_adapter(
        answers("<html>Too Many Requests</html>", status=429)
    )

    result = adapter.check(SUBJECT)

    assert result.status == CheckStatus.ERROR
    assert len(requests) == 3  # first try + 2 retries
    assert "busy (too many requests)" in result.explanation


def test_refused_api_key_is_not_retried() -> None:
    adapter, requests = make_adapter(answers("Unauthorized", status=401))

    result = adapter.check(SUBJECT)

    assert result.status == CheckStatus.ERROR
    assert len(requests) == 1
    assert "refused our API key" in result.explanation


def test_temporary_problem_then_answer() -> None:
    adapter, requests = make_adapter(answers(httpx.ConnectError("down"), extract()))

    result = adapter.check(SUBJECT)

    assert result.status == CheckStatus.OK
    assert len(requests) == 2


def test_not_reachable_is_error_with_plain_words() -> None:
    adapter, _ = make_adapter(answers(httpx.ConnectError("down")))

    result = adapter.check(SUBJECT)

    assert result.status == CheckStatus.ERROR
    assert result.explanation == (
        "The Firmenbuch could not be reached. The result was not confirmed. "
        "Please try again later."
    )


def test_answer_that_is_not_xml_is_error() -> None:
    adapter, _ = make_adapter(answers("not xml"))

    assert adapter.check(SUBJECT).status == CheckStatus.ERROR


def test_answer_without_extract_is_error() -> None:
    adapter, _ = make_adapter(
        answers('<env:Envelope xmlns:env="x"><env:Body/></env:Envelope>')
    )

    assert adapter.check(SUBJECT).status == CheckStatus.ERROR


def test_describe_unknown_error_never_sounds_like_ok() -> None:
    text = describe(CheckStatus.ERROR, {"error": "SOMETHING"})
    assert "not confirmed" in text


# --- fakes and settings -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("scenario", "status"),
    [
        (Scenario.OK, CheckStatus.OK),
        (Scenario.FINDING, CheckStatus.FINDING),
        (Scenario.TIMEOUT, CheckStatus.ERROR),
        (Scenario.MALFORMED, CheckStatus.ERROR),
    ],
)
def test_fake_answers_go_through_the_real_rules(
    scenario: Scenario, status: CheckStatus
) -> None:
    real, requests = make_adapter(answers(extract()), api_key=None)
    fake = FakeAdapter(real, scenario)

    result = fake.check(SUBJECT)

    assert result.status == status
    assert result.raw["fake"] is True
    assert requests == []


def test_enabled_with_key_or_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIRMENBUCH_API_KEY", raising=False)
    monkeypatch.delenv("FIRMENBUCH_ADAPTER", raising=False)
    assert not is_enabled()
    monkeypatch.setenv("FIRMENBUCH_ADAPTER", "fake-ok")
    assert is_enabled()
    monkeypatch.delenv("FIRMENBUCH_ADAPTER")
    monkeypatch.setenv("FIRMENBUCH_API_KEY", "token")
    assert is_enabled()
