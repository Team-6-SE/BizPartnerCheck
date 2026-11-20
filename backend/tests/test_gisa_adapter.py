"""The GISA adapter with fake SOAP answers: no internet and no API key needed.

The answers follow the ministry's SoapUI examples and XML structure file for the public
interface V2 (GetGewerbeV2, SearchPersonNat, "API-Key abgelaufen", "GISA-Zahl ungültig").
"""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime

import httpx2 as httpx
import pytest

from app.adapters.base import CheckStatus, CheckSubject, Scenario
from app.adapters.fake import FakeAdapter
from app.adapters.gisa import (
    ACTIVE,
    ENDED,
    GISA_ERROR,
    MAX_LICENCES,
    NO_API_KEY,
    SERVICE_NAMESPACE,
    SUSPENDED,
    UNKNOWN,
    GisaAdapter,
    describe,
    is_enabled,
    licence_state,
    licences,
    manager_of,
)
from app.adapters.limits import Limits

BASE_URL = "https://gisa.test/gisa-svc-public/GisaPublicV2.svc/soap"
API_KEY = "93057523-69c4-45fa-a596-47886a08cf7a"
FN = "123456a"
NOW = datetime(2026, 11, 19, 10, 0, tzinfo=UTC)
SUBJECT = CheckSubject(vat_number=None, register_number=FN)


def response(operation: str, inner: str) -> str:
    return (
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
        f'<{operation}Response xmlns="{SERVICE_NAMESPACE}">'
        f'<{operation}Result xmlns:i="http://www.w3.org/2001/XMLSchema-instance">'
        f"{inner}</{operation}Result></{operation}Response></s:Body></s:Envelope>"
    )


def search_answer(*numbers: str, ended: tuple[str, ...] = ()) -> str:
    """A hit list like the real one: no dates, ended licences only under <Historie>."""

    def hit(n: str) -> str:
        right = (
            f"<Berechtigung><GewerbeSchluessel>4701</GewerbeSchluessel>"
            f"<Wortlaut>Gewerbe {n}</Wortlaut></Berechtigung>"
        )
        if n in ended:
            right = f"<Historie>{right}</Historie>"
        return (
            f"<Gewerbe><GISAZahl>{n}</GISAZahl><BerechtigungDaten>{right}"
            "</BerechtigungDaten><InhaberDaten><Inhaber><JurPerson>"
            "<Firmenname>Muster Bau GmbH</Firmenname><FBNummer>0123456a</FBNummer>"
            "</JurPerson></Inhaber></InhaberDaten></Gewerbe>"
        )

    hits = "".join(hit(n) for n in numbers)
    return response("SearchPersonJur", f'<GewerbeListe xmlns="">{hits}</GewerbeListe>')


def right(
    trade: str,
    *,
    start: str = "2018-04-01",
    end: str = "",
    ruhend: bool = False,
    ruhend_von: str = "",
    ruhend_bis: str = "",
) -> str:
    end_xml = f"<EndigungDatum>{end}T00:00:00</EndigungDatum>" if end else ""
    von = f"<RuhendVon>{ruhend_von}T00:00:00</RuhendVon>" if ruhend_von else ""
    bis = f"<RuhendBis>{ruhend_bis}T00:00:00</RuhendBis>" if ruhend_bis else ""
    return (
        "<Berechtigung><GewerbeSchluessel>100</GewerbeSchluessel>"
        f"<Wortlaut>{trade}</Wortlaut><Behoerde><Bezeichnung>Magistrat der Stadt Krems"
        "</Bezeichnung><Kuerzel>301</Kuerzel></Behoerde>"
        f"<RechtswirksamAb>{start}T00:00:00</RechtswirksamAb>{end_xml}"
        "<IstIndustriebetrieb>false</IstIndustriebetrieb>"
        f"<Ruhend><IstRuhend>{str(ruhend).lower()}</IstRuhend>{bis}{von}</Ruhend>"
        "</Berechtigung>"
    )


MANAGER = (
    "<GeschaeftsfuehrerDaten><Geschaeftsfuehrer><NatPerson>"
    "<Familienname>Muster</Familienname><Vorname>Maria</Vorname>"
    "<GebDatum>1970-05-17T00:00:00</GebDatum><PersonID>99920279659</PersonID>"
    "<Titel>Ing.</Titel><NachTitel/></NatPerson>"
    "<RechtswirksamAb>2018-04-01T00:00:00</RechtswirksamAb></Geschaeftsfuehrer>"
    "<Historie><Geschaeftsfuehrer><NatPerson><Familienname>Alt</Familienname>"
    "<Vorname>Karl</Vorname></NatPerson><RechtswirksamAb>2010-01-01T00:00:00"
    "</RechtswirksamAb><EndigungDatum>2018-03-31T00:00:00</EndigungDatum>"
    "</Geschaeftsfuehrer></Historie></GeschaeftsfuehrerDaten>"
)


def gewerbe(number: str, rights: str, *, manager: str = MANAGER) -> str:
    """A GetGewerbeV2 answer like the ministry's example, with current and history."""
    return response(
        "GetGewerbeV2",
        f'<Gewerbe xmlns=""><GISAZahl>{number}</GISAZahl>'
        f"<BerechtigungDaten>{rights}</BerechtigungDaten>"
        "<InhaberDaten><Inhaber><JurPerson><PersonID>1</PersonID>"
        "<FBNummer>123456a</FBNummer><Firmenname>Muster Bau GmbH</Firmenname>"
        "</JurPerson><RechtswirksamAb>2018-04-01T00:00:00</RechtswirksamAb></Inhaber>"
        "</InhaberDaten><StandortDaten><Standort><Postadresse><PLZ>3500</PLZ>"
        "<Ort>Krems/Donau</Ort><Strassenname>Ringstraße</Strassenname>"
        "<Orientierungsnummer>12</Orientierungsnummer></Postadresse>"
        "<RechtswirksamAb>2019-07-30T00:00:00</RechtswirksamAb></Standort>"
        "<Historie><Standort><Postadresse><PLZ>4614</PLZ><Ort>Au an der Traun</Ort>"
        "</Postadresse><EndigungDatum>2019-07-29T00:00:00</EndigungDatum></Standort>"
        f"</Historie></StandortDaten>{manager}</Gewerbe>",
    )


def error(operation: str, code: str, text: str) -> str:
    return response(
        operation,
        '<Returncode xmlns="">ERROR</Returncode><MeldungListe xmlns=""><Meldung>'
        f"<Code>{code}</Code><Beschreibung>{text}</Beschreibung></Meldung>"
        "</MeldungListe>",
    )


Handler = Callable[[httpx.Request], httpx.Response]


def by_operation(
    search: str, details: dict[str, str] | None = None, status: int = 200
) -> Handler:
    """Answer SearchPersonJur with `search` and GetGewerbeV2 per GISA number."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if "SearchPersonJur" in body:
            return httpx.Response(status, text=search)
        for number, answer in (details or {}).items():
            if f"<GISAZahl>{number}</GISAZahl>" in body:
                return httpx.Response(200, text=answer)
        return httpx.Response(
            200, text=error("GetGewerbeV2", "1000", "GISA-Zahl nicht gefunden")
        )

    return handler


def make_adapter(
    handler: Handler, api_key: str | None = API_KEY
) -> tuple[GisaAdapter, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    adapter = GisaAdapter(
        BASE_URL,
        api_key,
        transport=httpx.MockTransport(record),
        limits=Limits(),
        sleep=lambda _seconds: None,
        now=lambda: NOW,
    )
    return adapter, requests


# --- requests -----------------------------------------------------------------------------


def test_requests_follow_the_soapui_examples() -> None:
    adapter, requests = make_adapter(
        by_operation(search_answer("111"), {"111": gewerbe("111", right("Baumeister"))})
    )

    adapter.check(SUBJECT)

    search, detail = (r.content.decode() for r in requests)
    assert f'xmlns:v2="{SERVICE_NAMESPACE}"' in search
    assert "<v2:SearchPersonJur><v2:input>" in search
    assert f"<Apikey>{API_KEY}</Apikey>" in search
    assert f"<Firmenbuchnummer>{FN}</Firmenbuchnummer>" in search
    # In the order of the WSDL, or the service ignores the fields.
    assert (
        f"<Apikey>{API_KEY}</Apikey><Firmenbuchnummer>{FN}</Firmenbuchnummer>"
        "<SearchAuslVermittler>false</SearchAuslVermittler>"
        "<SearchHistorisch>true</SearchHistorisch>"
        "<SearchPhonetisch>false</SearchPhonetisch>"
    ) in search
    assert "<v2:GetGewerbeV2><v2:input>" in detail
    assert "<GISAZahl>111</GISAZahl>" in detail
    assert requests[0].headers["SOAPAction"] == (
        '"http://gisa.wien.gv.at/public_svc/V2/IGisaPublic/SearchPersonJur"'
    )


def test_without_api_key_nothing_is_sent() -> None:
    adapter, requests = make_adapter(by_operation(search_answer()), api_key=None)

    result = adapter.check(SUBJECT)

    assert requests == []
    assert result.status == CheckStatus.ERROR
    assert result.raw["error"] == NO_API_KEY
    assert "not set up on this server yet" in result.explanation


def test_the_api_key_birth_dates_and_person_ids_are_never_stored() -> None:
    adapter, _ = make_adapter(
        by_operation(search_answer("111"), {"111": gewerbe("111", right("Baumeister"))})
    )

    stored = json.dumps(adapter.check(SUBJECT).raw, ensure_ascii=False)

    assert API_KEY not in stored
    assert "1970" not in stored
    assert "99920279659" not in stored


# --- licences and status rules ------------------------------------------------------------


def test_active_licence_is_ok_with_trade_number_start_and_manager() -> None:
    ended = f"<Historie>{right('Handelsgewerbe', start='2010-01-01', end='2024-12-31')}</Historie>"
    adapter, _ = make_adapter(
        by_operation(
            search_answer("111", "222"),
            {
                "111": gewerbe("111", right("Baumeister")),
                "222": gewerbe("222", ended, manager=""),
            },
        )
    )

    result = adapter.check(SUBJECT)

    assert result.status == CheckStatus.OK
    first, second = licences(result.raw)
    assert first["gisaNumber"] == "111"
    assert first["trade"] == "Baumeister"
    assert first["tradeKey"] == "100"
    assert first["authority"] == "Magistrat der Stadt Krems"
    assert first["state"] == ACTIVE
    assert first["start"] == "2018-04-01"
    # The current location, not the one from the history.
    assert first["location"] == "Ringstraße 12, 3500 Krems/Donau"
    assert first["owner"] == "Muster Bau GmbH"
    # The current responsible person, not the earlier one from the history.
    assert first["manager"] == {
        "name": "Ing. Maria Muster",
        "since": "2018-04-01",
        "end": None,
    }
    assert second["state"] == ENDED
    assert second["trade"] == "Handelsgewerbe"
    assert second["end"] == "2024-12-31"
    assert result.explanation == (
        "GISA lists 1 active licence for FN 123456a: Baumeister. "
        "Please check that they cover the planned work."
    )


def test_only_ended_or_suspended_licences_are_a_finding() -> None:
    ended = f"<Historie>{right('Handelsgewerbe', end='2024-12-31')}</Historie>"
    adapter, _ = make_adapter(
        by_operation(
            search_answer("111", "222"),
            {
                "111": gewerbe(
                    "111", right("Baumeister", ruhend=True, ruhend_von="2025-01-01")
                ),
                "222": gewerbe("222", ended),
            },
        )
    )

    result = adapter.check(SUBJECT)

    assert result.status == CheckStatus.FINDING
    assert "no active licence" in result.explanation
    assert "Baumeister (suspended (ruhend))" in result.explanation
    assert "Handelsgewerbe (ended)" in result.explanation
    assert licences(result.raw)[0]["suspendedFrom"] == "2025-01-01"


def test_no_licence_at_all_is_a_finding() -> None:
    adapter, requests = make_adapter(by_operation(search_answer()))

    result = adapter.check(SUBJECT)

    assert result.status == CheckStatus.FINDING
    assert result.raw["licences"] == []
    assert len(requests) == 1
    assert "GISA lists no business licence for FN 123456a" in result.explanation


def test_hit_without_detail_needs_a_review() -> None:
    # GetGewerbeV2 says "GISA-Zahl nicht gefunden": only the hit list data is known.
    adapter, _ = make_adapter(by_operation(search_answer("111")))

    result = adapter.check(SUBJECT)

    licence = result.raw["licences"][0]
    assert licence["trade"] == "Gewerbe 111"
    assert licence["detailMissing"] is True
    assert licences(result.raw)[0]["state"] == UNKNOWN
    assert result.status == CheckStatus.REVIEW


def test_current_licences_are_asked_in_detail_first() -> None:
    ended = tuple(str(n) for n in range(MAX_LICENCES))
    adapter, requests = make_adapter(
        by_operation(
            search_answer(*ended, "999", ended=ended),
            {"999": gewerbe("999", right("Baumeister"))},
        )
    )

    result = adapter.check(SUBJECT)

    asked = [r.content.decode() for r in requests[1:]]
    assert len(asked) == MAX_LICENCES
    assert any("<GISAZahl>999</GISAZahl>" in body for body in asked)
    last_ended = f"<GISAZahl>{MAX_LICENCES - 1}</GISAZahl>"
    assert not any(last_ended in body for body in asked)
    assert result.status == CheckStatus.OK
    # GISA's order is kept; the ended licence that was not asked is still ended.
    states = [licence["state"] for licence in licences(result.raw)]
    assert states[-1] == ACTIVE
    assert states[MAX_LICENCES - 1] == ENDED


def test_at_most_max_licences_are_asked_in_detail() -> None:
    numbers = [str(n) for n in range(MAX_LICENCES + 3)]
    adapter, requests = make_adapter(by_operation(search_answer(*numbers)))

    result = adapter.check(SUBJECT)

    assert len(requests) == 1 + MAX_LICENCES
    assert result.raw["licenceCount"] == MAX_LICENCES + 3
    assert len(result.raw["licences"]) == MAX_LICENCES + 3


@pytest.mark.parametrize(
    ("licence", "state"),
    [
        ({"start": "2020-01-01"}, ACTIVE),
        ({"start": "2020-01-01", "historic": True}, ENDED),
        ({"start": "2020-01-01", "end": "2026-01-01"}, ENDED),
        ({"start": "2020-01-01", "end": "2027-01-01"}, ACTIVE),
        ({"start": "2020-01-01", "suspended": True}, SUSPENDED),
        (
            {"start": "2020-01-01", "suspended": True, "suspendedUntil": "2027-01-01"},
            SUSPENDED,
        ),
        (
            {"start": "2020-01-01", "suspended": True, "suspendedUntil": "2026-01-01"},
            ACTIVE,
        ),
        ({"start": "2027-01-01"}, UNKNOWN),
        ({}, UNKNOWN),
    ],
)
def test_licence_state(licence: dict, state: str) -> None:
    assert licence_state(licence, date(2026, 11, 19)) == state


def test_ended_responsible_person_is_not_shown() -> None:
    licence = {
        "manager": {"name": "Karl Alt", "since": "2010-01-01", "end": "2018-03-31"}
    }

    assert manager_of(licence, date(2026, 11, 19)) is None


# --- errors -------------------------------------------------------------------------------


def test_wrong_or_expired_key_is_error_and_not_retried() -> None:
    adapter, requests = make_adapter(
        by_operation(
            error("SearchPersonJur", "300", "API-Key nicht gefunden oder abgelaufen")
        )
    )

    result = adapter.check(SUBJECT)

    assert result.status == CheckStatus.ERROR
    assert result.raw["error"] == GISA_ERROR
    assert len(requests) == 1
    assert "refused our API key" in result.explanation


def test_unexpected_gisa_error_is_retried() -> None:
    adapter, requests = make_adapter(
        by_operation(error("SearchPersonJur", "310", "Unerwarteter Fehler aufgetreten"))
    )

    result = adapter.check(SUBJECT)

    assert result.status == CheckStatus.ERROR
    assert len(requests) == 3
    assert "Unerwarteter Fehler aufgetreten" in result.explanation


def test_too_many_requests_is_retried_then_error() -> None:
    adapter, requests = make_adapter(by_operation("<html>busy</html>", status=429))

    result = adapter.check(SUBJECT)

    assert result.status == CheckStatus.ERROR
    assert len(requests) == 3
    assert "busy" in result.explanation


def test_not_reachable_is_error() -> None:
    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    adapter, _ = make_adapter(down)

    result = adapter.check(SUBJECT)

    assert result.status == CheckStatus.ERROR
    assert "GISA could not be reached" in result.explanation


def test_soap_fault_is_error() -> None:
    fault = (
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
        "<s:Fault><faultcode>s:Client</faultcode><faultstring>Bad action"
        "</faultstring></s:Fault></s:Body></s:Envelope>"
    )
    adapter, _ = make_adapter(by_operation(fault, status=500))

    result = adapter.check(SUBJECT)

    assert result.status == CheckStatus.ERROR


def test_answer_that_is_not_xml_is_error() -> None:
    adapter, _ = make_adapter(by_operation("not xml"))

    assert adapter.check(SUBJECT).status == CheckStatus.ERROR


def test_describe_unknown_error_never_sounds_like_ok() -> None:
    assert "not confirmed" in describe(CheckStatus.ERROR, {"error": "SOMETHING"})


# --- fakes and settings -------------------------------------------------------------------


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
    real, requests = make_adapter(by_operation(search_answer()), api_key=None)

    result = FakeAdapter(real, scenario).check(SUBJECT)

    assert result.status == status
    assert result.raw["fake"] is True
    assert requests == []


def test_enabled_with_key_or_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GISA_API_KEY", raising=False)
    monkeypatch.delenv("GISA_ADAPTER", raising=False)
    assert not is_enabled()
    monkeypatch.setenv("GISA_ADAPTER", "fake-finding")
    assert is_enabled()
    monkeypatch.delenv("GISA_ADAPTER")
    monkeypatch.setenv("GISA_API_KEY", "key")
    assert is_enabled()
