"""The HFU adapter with fake SOAP answers: no internet needed (S4.4)."""

from collections.abc import Callable
from datetime import UTC, datetime

import httpx2 as httpx
import pytest

from app.adapters.base import CheckStatus, CheckSubject, Scenario, SourceResult
from app.adapters.fake import FakeAdapter
from app.adapters.hfu import (
    NO_REQUESTER,
    SOAP_FAULT,
    HfuAdapter,
    build_request,
    company_name,
    describe,
    parse_response,
)
from app.adapters.limits import Limits

BASE_URL = "https://hfu.test/agh-ws-prod/DienstgeberAbfrageWS_3_0"
REQUESTER = "ATU99999999"
PARTNER = "ATU12345675"
# 23:30 UTC is already the next day in Vienna (CET): the reference date must follow Vienna.
NOW = datetime(2026, 11, 16, 23, 30, tzinfo=UTC)
TODAY_IN_VIENNA = "2026-11-17"


def result_xml(
    employer: str, sole_trader: str, name: str | None = "Muster EPU 2", note: str = ""
) -> str:
    name_xml = f"<auftragnehmerName>{name}</auftragnehmerName>" if name else ""
    note_xml = f"<hinweis>{note}</hinweis>" if note else ""
    return (
        "<auftragnehmerRS>"
        "<auftragnehmerHauptanschrift>3100 St. Pölten, Rathausplatz 6"
        "</auftragnehmerHauptanschrift>"
        f"{name_xml}"
        "<firmenbuchnummer>123456d</firmenbuchnummer>"
        f"<uid>{PARTNER}</uid>"
        "<einzelunternehmen><name>Baustoffe e.U.</name>"
        "<firmenbuchnummer>0000001</firmenbuchnummer></einzelunternehmen>"
        f"<hfuListeDgJN>{employer}</hfuListeDgJN>"
        f"<hfuListeEpuJN>{sole_trader}</hfuListeEpuJN>"
        f"{note_xml}"
        "</auftragnehmerRS>"
    )


def soap_response(*results: str) -> str:
    """An answer in the form of the service's own sample response."""
    return (
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soap:Body>"
        '<ns3:dienstgeberAbfragenResponse xmlns:ns2="AGHExternWS_3_0.extern_3_0.ws.agh.noegkk.sozvers.at" '
        'xmlns:ns3="http://AGHExternWS_3_0.extern_3_0.ws.agh.noegkk.sozvers.at/">'
        f"{''.join(results)}"
        "</ns3:dienstgeberAbfragenResponse></soap:Body></soap:Envelope>"
    )


FAULT = (
    '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
    "<soap:Body><soap:Fault><faultcode>soap:Server</faultcode>"
    "<faultstring>Es muss genau eines der Elemente dgnrAuftraggeber, "
    "vsnrAuftraggeber bzw. uidAuftraggeber befüllt sein.</faultstring>"
    "</soap:Fault></soap:Body></soap:Envelope>"
)

Handler = Callable[[httpx.Request], httpx.Response]


def make_adapter(handler: Handler, **options) -> tuple[HfuAdapter, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    options.setdefault("limits", Limits())  # defaults, whatever the environment says
    options.setdefault("now", lambda: NOW)
    adapter = HfuAdapter(
        BASE_URL,
        transport=httpx.MockTransport(record),
        sleep=lambda _seconds: None,
        **options,
    )
    return adapter, requests


def answers(*items: str | Exception, status: int = 200) -> Handler:
    queue = list(items)

    def handler(request: httpx.Request) -> httpx.Response:
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return httpx.Response(status, text=item, headers={"Content-Type": "text/xml"})

    return handler


def check(adapter: HfuAdapter, requester: str | None = REQUESTER) -> SourceResult:
    return adapter.check(CheckSubject(vat_number=PARTNER, requester_vat=requester))


# --- the request ----------------------------------------------------------------


def test_request_is_soap_with_our_uid_the_partner_uid_and_todays_date() -> None:
    adapter, requests = make_adapter(answers(soap_response(result_xml("J", "N"))))

    check(adapter)

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == BASE_URL
    assert request.headers["Content-Type"].startswith("text/xml")
    # The service rejects requests with a SOAPAction header.
    assert "SOAPAction" not in request.headers
    body = request.content.decode()
    assert "<agh:dienstgeberAbfragen>" in body
    assert f"<uidAuftraggeber>{REQUESTER}</uidAuftraggeber>" in body
    assert f"<stichtag>{TODAY_IN_VIENNA}</stichtag>" in body
    assert f"<uidAuftragnehmer>{PARTNER}</uidAuftragnehmer>" in body
    assert "dgnrAuftraggeber" not in body


def test_request_escapes_xml() -> None:
    body = build_request("ATU1<&>", "ATU2", datetime(2026, 1, 2, tzinfo=UTC).date())

    assert "<uidAuftraggeber>ATU1&lt;&amp;&gt;</uidAuftraggeber>" in body
    assert "<stichtag>2026-01-02</stichtag>" in body


# --- answers --------------------------------------------------------------------


def test_listed_as_employer_is_ok() -> None:
    adapter, _ = make_adapter(answers(soap_response(result_xml("J", "N"))))

    result = check(adapter)

    assert result.status == CheckStatus.OK
    assert result.raw["stichtag"] == TODAY_IN_VIENNA
    assert result.raw["requester"] == {"uidAuftraggeber": REQUESTER}
    assert result.raw["checked"] == {"uidAuftragnehmer": PARTNER}
    entry = result.raw["auftragnehmerRS"][0]
    assert entry["hfuListeDgJN"] == "J"
    assert entry["auftragnehmerName"] == "Muster EPU 2"
    assert entry["uid"] == PARTNER
    assert entry["einzelunternehmen"] == [
        {"name": "Baustoffe e.U.", "firmenbuchnummer": "0000001"}
    ]
    assert "httpStatus" not in result.raw
    assert "is on the HFU list as of 17 Nov 2026 as employer" in result.explanation
    assert "(Muster EPU 2)" in result.explanation
    assert "no withholding" in result.explanation


def test_listed_as_sole_trader_is_ok() -> None:
    adapter, _ = make_adapter(answers(soap_response(result_xml("N", "J"))))

    result = check(adapter)

    assert result.status == CheckStatus.OK
    assert "as one-person company (EPU)" in result.explanation


def test_not_listed_is_finding_with_withholding_hint() -> None:
    adapter, requests = make_adapter(answers(soap_response(result_xml("N", "N"))))

    result = check(adapter)

    assert result.status == CheckStatus.FINDING
    assert len(requests) == 1  # a clear answer is not asked again
    assert "is not on the HFU list as of 17 Nov 2026" in result.explanation
    assert "A withholding may apply to payments" in result.explanation
    assert "not proof of a problem" in result.explanation


def test_note_from_the_service_is_shown() -> None:
    adapter, _ = make_adapter(
        answers(soap_response(result_xml("N", "N", note="DGNR stillgelegt")))
    )

    result = check(adapter)

    assert "Note from the ÖGK: DGNR stillgelegt" in result.explanation


def test_missing_company_name_is_fine() -> None:
    adapter, _ = make_adapter(answers(soap_response(result_xml("J", "N", name=None))))

    result = check(adapter)

    assert result.status == CheckStatus.OK
    assert company_name(result.raw) is None
    assert "This partner is on the HFU list" in result.explanation


# --- no requester ---------------------------------------------------------------


def test_without_organisation_vat_number_nothing_is_sent() -> None:
    adapter, requests = make_adapter(answers(soap_response(result_xml("J", "N"))))

    result = check(adapter, requester=None)

    assert result.status == CheckStatus.ERROR
    assert requests == []
    assert result.raw["error"] == NO_REQUESTER
    assert result.raw["stichtag"] == TODAY_IN_VIENNA
    assert "organisation's own VAT number is not set" in result.explanation
    assert "organisation settings" in result.explanation
    assert "try again" not in result.explanation.lower()


# --- errors: never OK -----------------------------------------------------------


def test_soap_fault_is_error_and_not_asked_again() -> None:
    adapter, requests = make_adapter(answers(FAULT, status=500))

    result = check(adapter)

    assert result.status == CheckStatus.ERROR
    assert len(requests) == 1
    assert result.raw["error"] == SOAP_FAULT
    assert result.raw["httpStatus"] == 500
    assert "rejected the request: Es muss genau eines" in result.explanation
    assert "not confirmed" in result.explanation
    assert "try again" not in result.explanation.lower()


def test_server_error_without_fault_is_retried() -> None:
    adapter, requests = make_adapter(
        answers("<html>Service Unavailable</html>", "<html/>", "<html/>", status=503)
    )

    result = check(adapter)

    assert result.status == CheckStatus.ERROR
    assert len(requests) == 3  # first try + 2 retries
    assert result.raw["httpStatus"] == 503


def test_client_error_is_not_retried() -> None:
    adapter, requests = make_adapter(answers("Not Found", status=404))

    result = check(adapter)

    assert result.status == CheckStatus.ERROR
    assert len(requests) == 1
    assert result.raw["error"] == "BAD_RESPONSE"


def test_timeout_gives_error_never_ok() -> None:
    timeout = httpx.ReadTimeout("timed out")
    adapter, requests = make_adapter(answers(timeout, timeout, timeout))

    result = check(adapter)

    assert result.status == CheckStatus.ERROR
    assert result.raw["error"] == "NO_ANSWER_IN_TIME"
    assert len(requests) == 3
    assert "did not answer in time" in result.explanation


def test_not_reachable_gives_error() -> None:
    down = httpx.ConnectError("connection refused")
    adapter, _ = make_adapter(answers(down, down, down))

    result = check(adapter)

    assert result.status == CheckStatus.ERROR
    assert result.raw["error"] == "NOT_REACHABLE"
    assert "could not be reached" in result.explanation


@pytest.mark.parametrize(
    "body",
    [
        "<html>maintenance</html>",
        "not xml at all <<<",
        soap_response(),  # no entry for the partner
        soap_response(result_xml("X", "N")),  # unknown flag
        soap_response(
            "<auftragnehmerRS><hfuListeDgJN>N</hfuListeDgJN></auftragnehmerRS>"
        ),
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body/></soap:Envelope>',
    ],
)
def test_unclear_answers_are_error(body: str) -> None:
    adapter, _ = make_adapter(answers(body))

    result = check(adapter)

    assert result.status == CheckStatus.ERROR
    assert isinstance(result.raw, dict)
    assert "not confirmed" in result.explanation


def test_parse_response_reads_fault_details() -> None:
    parsed = parse_response(FAULT)

    assert parsed["error"] == SOAP_FAULT
    assert parsed["faultcode"] == "soap:Server"
    assert parsed["faultstring"].startswith("Es muss genau eines")


def test_describe_without_details_is_still_clear() -> None:
    assert "not confirmed" in describe(CheckStatus.ERROR, {"something": "new"})
    assert "on the HFU list" in describe(CheckStatus.OK, {})
    assert "withholding" in describe(CheckStatus.FINDING, {})


# --- fake adapter (HFU_ADAPTER=fake-...) ---------------------------------------


@pytest.mark.parametrize(
    ("scenario", "status"),
    [(Scenario.OK, CheckStatus.OK), (Scenario.FINDING, CheckStatus.FINDING)],
)
def test_fake_answers_are_marked(scenario: Scenario, status: CheckStatus) -> None:
    adapter, requests = make_adapter(answers(FAULT))
    fake = FakeAdapter(adapter, scenario)

    result = fake.check(CheckSubject(vat_number=PARTNER, requester_vat=REQUESTER))

    assert result.status == status
    assert result.raw["fake"] is True
    assert result.raw["stichtag"] == TODAY_IN_VIENNA
    assert "fake HFU" in result.raw["auftragnehmerRS"][0]["auftragnehmerName"]
    assert requests == []  # nothing was sent
