"""The HFU adapter with fake SOAP answers: no internet needed."""

from collections.abc import Callable
from datetime import UTC, datetime

import httpx2 as httpx
import pytest

from app.adapters.base import CheckStatus, CheckSubject, Scenario, SourceResult
from app.adapters.fake import FakeAdapter
from app.adapters.hfu import NO_REQUESTER, SOAP_FAULT, HfuAdapter, describe
from app.adapters.limits import Limits

BASE_URL = "https://hfu.test/agh-ws-prod/DienstgeberAbfrageWS_3_0"
REQUESTER = "ATU99999999"
PARTNER = "ATU12345675"
# 23:30 UTC is already the next day in Vienna: the reference date must follow Vienna.
NOW = datetime(2026, 11, 16, 23, 30, tzinfo=UTC)
TODAY_IN_VIENNA = "2026-11-17"


def result_xml(employer: str, sole_trader: str, note: str = "") -> str:
    note_xml = f"<hinweis>{note}</hinweis>" if note else ""
    return (
        "<auftragnehmerRS>"
        "<auftragnehmerHauptanschrift>3100 St. Pölten</auftragnehmerHauptanschrift>"
        "<auftragnehmerName>Muster EPU 2</auftragnehmerName>"
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
    """Like the sample response in the ÖGK interface description."""
    return (
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soap:Body><ns3:dienstgeberAbfragenResponse "
        'xmlns:ns3="http://AGHExternWS_3_0.extern_3_0.ws.agh.noegkk.sozvers.at/">'
        f"{''.join(results)}"
        "</ns3:dienstgeberAbfragenResponse></soap:Body></soap:Envelope>"
    )


FAULT = (
    '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
    "<soap:Body><soap:Fault><faultcode>soap:Server</faultcode>"
    "<faultstring>Es muss genau eines der Elemente befüllt sein.</faultstring>"
    "</soap:Fault></soap:Body></soap:Envelope>"
)

Handler = Callable[[httpx.Request], httpx.Response]


def make_adapter(handler: Handler, **options) -> tuple[HfuAdapter, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    options.setdefault("limits", Limits())  # defaults, whatever the environment says
    adapter = HfuAdapter(
        BASE_URL,
        transport=httpx.MockTransport(record),
        sleep=lambda _seconds: None,
        now=lambda: NOW,
        **options,
    )
    return adapter, requests


def answers(*items: str | Exception, status: int = 200) -> Handler:
    """Give these answers one after another (an exception is raised instead)."""
    queue = list(items)

    def handler(request: httpx.Request) -> httpx.Response:
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return httpx.Response(status, text=item)

    return handler


def check(adapter: HfuAdapter, requester: str | None = REQUESTER) -> SourceResult:
    return adapter.check(CheckSubject(vat_number=PARTNER, requester_vat=requester))


def test_request_has_our_uid_the_partner_uid_and_todays_date() -> None:
    adapter, requests = make_adapter(answers(soap_response(result_xml("J", "N"))))

    check(adapter)

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == BASE_URL
    assert request.headers["Content-Type"].startswith("text/xml")
    assert "SOAPAction" not in request.headers  # the service rejects it
    body = request.content.decode()
    assert "<agh:dienstgeberAbfragen>" in body
    assert f"<uidAuftraggeber>{REQUESTER}</uidAuftraggeber>" in body
    assert f"<stichtag>{TODAY_IN_VIENNA}</stichtag>" in body
    assert f"<uidAuftragnehmer>{PARTNER}</uidAuftragnehmer>" in body


def test_listed_as_employer_is_ok() -> None:
    adapter, _ = make_adapter(answers(soap_response(result_xml("J", "N"))))

    result = check(adapter)

    assert result.status == CheckStatus.OK
    assert result.raw["stichtag"] == TODAY_IN_VIENNA
    assert result.raw["checked"] == {"uidAuftragnehmer": PARTNER}
    entry = result.raw["auftragnehmerRS"][0]
    assert entry["hfuListeDgJN"] == "J"
    assert entry["auftragnehmerName"] == "Muster EPU 2"
    assert entry["einzelunternehmen"] == [
        {"name": "Baustoffe e.U.", "firmenbuchnummer": "0000001"}
    ]
    assert "is on the HFU list as of 17 Nov 2026 as employer" in result.explanation
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


def test_without_organisation_vat_number_nothing_is_sent() -> None:
    adapter, requests = make_adapter(answers(soap_response(result_xml("J", "N"))))

    result = check(adapter, requester=None)

    assert result.status == CheckStatus.ERROR
    assert requests == []
    assert result.raw["error"] == NO_REQUESTER
    assert "organisation's own VAT number is not set" in result.explanation
    assert "try again" not in result.explanation.lower()


def test_soap_fault_is_error_and_not_asked_again() -> None:
    adapter, requests = make_adapter(answers(FAULT, status=500))

    result = check(adapter)

    assert result.status == CheckStatus.ERROR
    assert len(requests) == 1
    assert result.raw["error"] == SOAP_FAULT
    assert "rejected the request: Es muss genau eines" in result.explanation
    assert "try again" not in result.explanation.lower()


def test_server_error_without_fault_is_retried() -> None:
    adapter, requests = make_adapter(
        answers("<html/>", "<html/>", "<html/>", status=503)
    )

    result = check(adapter)

    assert result.status == CheckStatus.ERROR
    assert len(requests) == 3  # first try + 2 retries


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
    ],
)
def test_unclear_answers_are_error(body: str) -> None:
    adapter, _ = make_adapter(answers(body))

    result = check(adapter)

    assert result.status == CheckStatus.ERROR
    assert "not confirmed" in result.explanation


def test_describe_without_details_is_still_clear() -> None:
    assert "not confirmed" in describe(CheckStatus.ERROR, {"something": "new"})
    assert "on the HFU list" in describe(CheckStatus.OK, {})
    assert "withholding" in describe(CheckStatus.FINDING, {})


@pytest.mark.parametrize(
    ("scenario", "status"),
    [(Scenario.OK, CheckStatus.OK), (Scenario.FINDING, CheckStatus.FINDING)],
)
def test_fake_answers_are_marked(scenario: Scenario, status: CheckStatus) -> None:
    adapter, requests = make_adapter(answers(FAULT))

    result = FakeAdapter(adapter, scenario).check(
        CheckSubject(vat_number=PARTNER, requester_vat=REQUESTER)
    )

    assert result.status == status
    assert result.raw["fake"] is True
    assert requests == []  # nothing was sent
