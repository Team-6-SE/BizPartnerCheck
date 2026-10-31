"""VIES: the EU Commission service that says whether a VAT number is valid.

We use the public REST API (no key needed):

    GET {base_url}/ms/{country_code}/vat/{number}
    e.g. /ms/AT/vat/U33864707

The answer is JSON. The two fields we rely on:

    {"isValid": true, "userError": "VALID", "name": "...", "address": "...", ...}

`isValid` is also false when VIES could not ask the country (e.g. `userError` is
"MS_UNAVAILABLE" or "TIMEOUT"). So a number is only INVALID when VIES says
`userError: "INVALID"`. Everything we cannot read clearly is ERROR, never VALID.

Details and the reasons for these choices: docs/vies.md
"""

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx2 as httpx

DEFAULT_BASE_URL = "https://ec.europa.eu/taxation_customs/vies/rest-api"
SOURCE = "VIES"

# Limits from docs/architecture.md: 8 s per call, max. 2 retries, 30 s in total.
TIMEOUT_SECONDS = 8.0
MAX_RETRIES = 2
DEADLINE_SECONDS = 30.0
RETRY_DELAY_SECONDS = 0.5
MIN_ATTEMPT_SECONDS = 1.0

# VIES answers that may go away when we ask again a moment later.
TEMPORARY_ERRORS = frozenset(
    {
        "SERVICE_UNAVAILABLE",
        "MS_UNAVAILABLE",
        "TIMEOUT",
        "GLOBAL_MAX_CONCURRENT_REQ",
        "GLOBAL_MAX_CONCURRENT_REQ_TIME",
        "MS_MAX_CONCURRENT_REQ",
        "MS_MAX_CONCURRENT_REQ_TIME",
    }
)

# Our own codes for problems before VIES gave a usable answer.
NO_ANSWER_IN_TIME = "NO_ANSWER_IN_TIME"
NOT_REACHABLE = "NOT_REACHABLE"
BAD_RESPONSE = "BAD_RESPONSE"


class CheckStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ViesResult:
    status: CheckStatus
    # The VIES answer as we received it, or our own description of what went wrong.
    raw: dict[str, Any]


@dataclass(frozen=True)
class _Attempt:
    result: ViesResult
    try_again: bool


class ViesAdapter:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = TIMEOUT_SECONDS,
        max_retries: int = MAX_RETRIES,
        deadline: float = DEADLINE_SECONDS,
        retry_delay: float = RETRY_DELAY_SECONDS,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.deadline = deadline
        self.retry_delay = retry_delay
        # Tests pass a fake transport, so they never need the internet.
        self._transport = transport
        self._clock = clock
        self._sleep = sleep

    def check(self, vat_number: str) -> ViesResult:
        """Check a normalised VAT number such as "ATU12345678"."""
        country_code, number = vat_number[:2], vat_number[2:]
        url = f"{self.base_url}/ms/{country_code}/vat/{number}"
        started = self._clock()

        with httpx.Client(transport=self._transport) as client:
            attempt = 0
            while True:
                remaining = self.deadline - (self._clock() - started)
                outcome = self._ask(client, url, min(self.timeout, remaining))
                if not outcome.try_again or attempt >= self.max_retries:
                    return outcome.result
                delay = self.retry_delay * (attempt + 1)
                time_left = self.deadline - (self._clock() - started) - delay
                if time_left < MIN_ATTEMPT_SECONDS:
                    # Not enough time left for another useful attempt.
                    return outcome.result
                self._sleep(delay)
                attempt += 1

    def _ask(self, client: httpx.Client, url: str, timeout: float) -> _Attempt:
        try:
            response = client.get(
                url, headers={"Accept": "application/json"}, timeout=timeout
            )
        except httpx.TimeoutException:
            return _error(
                NO_ANSWER_IN_TIME, f"No answer within {round(timeout, 1):g} s.", True
            )
        except httpx.HTTPError as exc:
            return _error(NOT_REACHABLE, type(exc).__name__, True)

        try:
            body = response.json()
        except ValueError:
            body = None

        if response.status_code >= 400 or not isinstance(body, dict):
            temporary = response.status_code >= 500 or response.status_code == 429
            raw = (
                body
                if isinstance(body, dict)
                else {"error": BAD_RESPONSE, "message": response.text[:500]}
            )
            raw = {**raw, "httpStatus": response.status_code}
            return _Attempt(ViesResult(CheckStatus.ERROR, raw), temporary)

        return _read_answer(body)


def _error(code: str, message: str, try_again: bool) -> _Attempt:
    return _Attempt(
        ViesResult(CheckStatus.ERROR, {"error": code, "message": message}), try_again
    )


def _read_answer(body: dict[str, Any]) -> _Attempt:
    is_valid = body.get("isValid")
    user_error = body.get("userError")

    if is_valid is True and user_error in (None, "VALID"):
        return _Attempt(ViesResult(CheckStatus.VALID, body), False)
    if is_valid is False and user_error == "INVALID":
        return _Attempt(ViesResult(CheckStatus.INVALID, body), False)
    return _Attempt(ViesResult(CheckStatus.ERROR, body), user_error in TEMPORARY_ERRORS)


def error_code(raw: dict[str, Any]) -> str | None:
    """The reason of an ERROR result, e.g. "MS_UNAVAILABLE"."""
    for key in ("error", "userError"):
        if isinstance(raw.get(key), str):
            return raw[key]
    wrappers = raw.get("errorWrappers")
    if isinstance(wrappers, list) and wrappers and isinstance(wrappers[0], dict):
        return wrappers[0].get("error")
    return None


def company_name(raw: dict[str, Any]) -> str | None:
    """Registered name from VIES; some countries do not share it ("---")."""
    name = raw.get("name")
    if isinstance(name, str) and name.strip() not in ("", "---"):
        return name.strip()
    return None


_ERROR_MESSAGES = {
    NO_ANSWER_IN_TIME: "VIES did not answer in time.",
    NOT_REACHABLE: "VIES could not be reached.",
    "TIMEOUT": "The tax office of this country did not answer VIES in time.",
    "MS_UNAVAILABLE": "The tax office of this country is not available in VIES right now.",
    "SERVICE_UNAVAILABLE": "VIES is not available right now.",
    "GLOBAL_MAX_CONCURRENT_REQ": "VIES is busy right now.",
    "GLOBAL_MAX_CONCURRENT_REQ_TIME": "VIES is busy right now.",
    "MS_MAX_CONCURRENT_REQ": "The tax office of this country is busy right now.",
    "MS_MAX_CONCURRENT_REQ_TIME": "The tax office of this country is busy right now.",
    "INVALID_INPUT": "VIES did not accept this VAT number.",
}


def describe(status: CheckStatus, raw: dict[str, Any]) -> str:
    """One sentence for people: what the result means and what to do."""
    if status == CheckStatus.VALID:
        return "VIES confirms that this VAT number is valid."
    if status == CheckStatus.INVALID:
        return "VIES says this VAT number is not valid (not registered or no longer active)."
    reason = _ERROR_MESSAGES.get(
        error_code(raw) or "", "VIES could not check the number."
    )
    return f"{reason} The number was not confirmed. Please try again later."


def get_vies_adapter() -> ViesAdapter:
    """FastAPI dependency. VIES_BASE_URL can point to a stub for staging/load tests."""
    return ViesAdapter(os.environ.get("VIES_BASE_URL") or DEFAULT_BASE_URL)
