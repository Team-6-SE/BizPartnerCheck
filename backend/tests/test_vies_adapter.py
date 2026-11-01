"""The VIES adapter with fake HTTP answers: no internet needed."""

from collections.abc import Callable

import httpx2 as httpx
import pytest

from app.adapters.vies import (
    CheckStatus,
    ViesAdapter,
    company_name,
    describe,
    error_code,
)

BASE_URL = "https://vies.test/rest-api"

VALID = {
    "isValid": True,
    "requestDate": "2026-10-31T13:46:27.800Z",
    "userError": "VALID",
    "name": "Red Bull GmbH",
    "address": "Am Brunnen 1\nAT-5330 Fuschl/See",
    "requestIdentifier": "",
    "originalVatNumber": "U33864707",
    "vatNumber": "U33864707",
}

INVALID = {
    "isValid": False,
    "requestDate": "2026-10-31T13:46:27.800Z",
    "userError": "INVALID",
    "name": "---",
    "address": "---",
    "vatNumber": "U12345678",
}


def unavailable(code: str) -> dict:
    # VIES also sends isValid: false when it could not ask the country.
    return {"isValid": False, "userError": code, "name": "---", "address": "---"}


Handler = Callable[[httpx.Request], httpx.Response]


def make_adapter(
    handler: Handler, **options
) -> tuple[ViesAdapter, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    adapter = ViesAdapter(
        BASE_URL,
        transport=httpx.MockTransport(record),
        sleep=lambda _seconds: None,
        **options,
    )
    return adapter, requests


def answers(*items: dict | Exception) -> Handler:
    """Give these answers one after another (an exception is raised instead)."""
    queue = list(items)

    def handler(request: httpx.Request) -> httpx.Response:
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return httpx.Response(200, json=item)

    return handler


def test_valid_number() -> None:
    adapter, requests = make_adapter(answers(VALID))

    result = adapter.check("ATU33864707")

    assert result.status == CheckStatus.VALID
    assert result.raw == VALID
    assert len(requests) == 1
    assert str(requests[0].url) == f"{BASE_URL}/ms/AT/vat/U33864707"


def test_invalid_number() -> None:
    adapter, requests = make_adapter(answers(INVALID))

    result = adapter.check("ATU12345678")

    assert result.status == CheckStatus.INVALID
    assert result.raw == INVALID
    assert len(requests) == 1  # a clear answer is not asked again


def test_timeout_gives_error_never_valid() -> None:
    timeout = httpx.ReadTimeout("timed out")
    adapter, requests = make_adapter(answers(timeout, timeout, timeout))

    result = adapter.check("ATU33864707")

    assert result.status == CheckStatus.ERROR
    assert result.raw["error"] == "NO_ANSWER_IN_TIME"
    assert len(requests) == 3  # first try + 2 retries


def test_timeout_then_answer_uses_the_answer() -> None:
    adapter, requests = make_adapter(answers(httpx.ConnectTimeout("slow"), VALID))

    result = adapter.check("ATU33864707")

    assert result.status == CheckStatus.VALID
    assert len(requests) == 2


def test_not_reachable_gives_error() -> None:
    down = httpx.ConnectError("connection refused")
    adapter, _ = make_adapter(answers(down, down, down))

    result = adapter.check("ATU33864707")

    assert result.status == CheckStatus.ERROR
    assert result.raw["error"] == "NOT_REACHABLE"


@pytest.mark.parametrize(
    "code",
    ["MS_UNAVAILABLE", "TIMEOUT", "SERVICE_UNAVAILABLE", "MS_MAX_CONCURRENT_REQ"],
)
def test_country_not_available_is_error_not_invalid(code: str) -> None:
    adapter, requests = make_adapter(answers(*[unavailable(code)] * 3))

    result = adapter.check("ATU33864707")

    assert result.status == CheckStatus.ERROR
    assert result.raw["userError"] == code
    assert len(requests) == 3  # temporary problem: asked again


def test_permanent_vies_error_is_not_asked_again() -> None:
    adapter, requests = make_adapter(answers(unavailable("INVALID_INPUT")))

    result = adapter.check("ATU33864707")

    assert result.status == CheckStatus.ERROR
    assert len(requests) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="Internal Server Error"),
        httpx.Response(503, json={"errorWrappers": [{"error": "SERVICE_UNAVAILABLE"}]}),
        httpx.Response(200, text="<html>maintenance</html>"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, json={"isValid": "yes"}),
        httpx.Response(200, json={}),
    ],
)
def test_unexpected_answers_give_error(response: httpx.Response) -> None:
    adapter, _ = make_adapter(lambda _request: response)

    result = adapter.check("ATU33864707")

    assert result.status == CheckStatus.ERROR
    assert isinstance(result.raw, dict)


def test_http_error_keeps_status_and_body() -> None:
    adapter, requests = make_adapter(
        lambda _request: httpx.Response(404, text="Not Found")
    )

    result = adapter.check("ATU33864707")

    assert result.status == CheckStatus.ERROR
    assert result.raw == {
        "error": "BAD_RESPONSE",
        "message": "Not Found",
        "httpStatus": 404,
    }
    assert len(requests) == 1  # 4xx will not change when asked again


def test_overall_time_limit_stops_retries() -> None:
    now = [0.0]

    def slow(_request: httpx.Request) -> httpx.Response:
        now[0] += 20.0  # every call takes 20 s
        raise httpx.ReadTimeout("timed out")

    adapter, requests = make_adapter(slow, clock=lambda: now[0], deadline=30.0)

    result = adapter.check("ATU33864707")

    assert result.status == CheckStatus.ERROR
    assert len(requests) == 2  # a third try would end after the 30 s limit
    assert now[0] <= 40.0


def test_greece_uses_el_and_northern_ireland_xi() -> None:
    adapter, requests = make_adapter(answers(VALID, VALID))

    adapter.check("EL123456789")
    adapter.check("XI123456789")

    assert requests[0].url.path.endswith("/ms/EL/vat/123456789")
    assert requests[1].url.path.endswith("/ms/XI/vat/123456789")


def test_helpers_for_people() -> None:
    assert company_name(VALID) == "Red Bull GmbH"
    assert company_name(INVALID) is None
    assert error_code(unavailable("MS_UNAVAILABLE")) == "MS_UNAVAILABLE"
    assert error_code({"errorWrappers": [{"error": "IP_BLOCKED"}]}) == "IP_BLOCKED"
    assert "valid" in describe(CheckStatus.VALID, VALID)
    assert "not valid" in describe(CheckStatus.INVALID, INVALID)
    message = describe(CheckStatus.ERROR, {"error": "NO_ANSWER_IN_TIME"})
    assert "did not answer in time" in message
    assert "not confirmed" in message
    assert "not confirmed" in describe(CheckStatus.ERROR, {"something": "new"})
