"""VIES: the EU Commission service that says whether a VAT number is valid.

We use the public REST API (no key needed):

    GET {base_url}/ms/{country_code}/vat/{number}
    e.g. /ms/AT/vat/U33864707

The answer is JSON. The two fields we rely on:

    {"isValid": true, "userError": "VALID", "name": "...", "address": "...", ...}

`isValid` is also false when VIES could not ask the country (e.g. `userError` is
"MS_UNAVAILABLE" or "TIMEOUT"). So a number is only invalid (FINDING) when VIES says
`userError: "INVALID"`. Everything we cannot read clearly is ERROR, never OK.

Time limits, retries and "no answer" handling come from app/adapters/base.py.
Details and the reasons for these choices: docs/vies.md
"""

import os
from typing import Any

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

DEFAULT_BASE_URL = "https://ec.europa.eu/taxation_customs/vies/rest-api"
SOURCE = "VIES"

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


class ViesAdapter(SourceAdapter):
    source = SOURCE

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        transport: httpx.BaseTransport | None = None,
        **options: Any,
    ) -> None:
        super().__init__(**options)
        self.base_url = base_url.rstrip("/")
        # Tests pass a fake transport, so they never need the internet.
        self._transport = transport

    def query(self, subject: CheckSubject, timeout: float) -> dict[str, Any]:
        """Ask VIES once about a normalised VAT number such as "ATU12345678"."""
        vat_number = subject.vat_number
        if not vat_number:
            # The API refuses such partners before; this only guards against bugs.
            raise ValueError("VIES needs a VAT number")
        country_code, number = vat_number[:2], vat_number[2:]
        requester = subject.requester_vat
        headers = {"Accept": "application/json"}
        with httpx.Client(transport=self._transport) as client:
            if requester:
                response = client.post(
                    f"{self.base_url}/check-vat-number",
                    json={
                        "countryCode": country_code,
                        "vatNumber": number,
                        "requesterMemberStateCode": requester[:2],
                        "requesterNumber": requester[2:],
                    },
                    headers=headers,
                    timeout=timeout,
                )
            else:
                response = client.get(
                    f"{self.base_url}/ms/{country_code}/vat/{number}",
                    headers=headers,
                    timeout=timeout,
                )

        try:
            body = response.json()
        except ValueError:
            body = None

        if response.status_code >= 400 or not isinstance(body, dict):
            raw = (
                body
                if isinstance(body, dict)
                else {"error": BAD_RESPONSE, "message": response.text[:500]}
            )
            # httpStatus marks an answer that was not a normal VIES result.
            return {**raw, "httpStatus": response.status_code}
        return body

    def interpret(self, raw: dict[str, Any]) -> Interpretation:
        http_status = raw.get("httpStatus")
        if isinstance(http_status, int):
            # 5xx and 429 may go away; other HTTP errors will not change when asked again.
            temporary = http_status >= 500 or http_status == 429
            return Interpretation(CheckStatus.ERROR, try_again=temporary)

        is_valid = raw.get("isValid", raw.get("valid"))
        user_error = raw.get("userError")
        if is_valid is True and user_error in (None, "VALID"):
            return Interpretation(CheckStatus.OK)
        if is_valid is False and user_error == "INVALID":
            return Interpretation(CheckStatus.FINDING)
        return Interpretation(
            CheckStatus.ERROR, try_again=user_error in TEMPORARY_ERRORS
        )

    def describe(self, status: CheckStatus, raw: dict[str, Any]) -> str:
        return describe(status, raw)
    
    def sample_answer(self, scenario: Scenario, subject: CheckSubject) -> dict[str, Any]:
        number = (subject.vat_number or "")[2:]
        if scenario == Scenario.FINDING:
            return {
                "isValid": False,
                "userError": "INVALID",
                "name": "---",
                "address": "---",
                "vatNumber": number,
                "requestIdentifier": "FAKE-CONSULT-0001" if subject.requester_vat else "",
            }
        return {
            "isValid": True,
            "userError": "VALID",
            "name": "Muster Bau GmbH (fake VIES)",
            "address": "Hauptstrasse 1\nAT-1010 Wien",
            "vatNumber": number,
        }


def error_code(raw: dict[str, Any]) -> str | None:
    """The reason of an ERROR result, e.g. "MS_UNAVAILABLE"."""
    for key in ("error", "userError"):
        if isinstance(raw.get(key), str):
            return raw[key]
    wrappers = raw.get("errorWrappers")
    if isinstance(wrappers, list) and wrappers and isinstance(wrappers[0], dict):
        return wrappers[0].get("error")
    return None


def _clean(value: Any) -> str | None:
    if isinstance(value, str) and value.strip() not in ("", "---"):
        return value.strip()
    return None


def company_name(raw: dict[str, Any]) -> str | None:
    return _clean(raw.get("name"))


def registered_address(raw: dict[str, Any]) -> str | None:
    return _clean(raw.get("address"))


def consultation_number(raw: dict[str, Any]) -> str | None:
    return _clean(raw.get("requestIdentifier"))


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
    if status == CheckStatus.OK:
        return "VIES confirms that this VAT number is valid."
    if status == CheckStatus.FINDING:
        return "VIES says this VAT number is not valid (not registered or no longer active)."
    reason = _ERROR_MESSAGES.get(
        error_code(raw) or "", "VIES could not check the number."
    )
    return f"{reason} The number was not confirmed. Please try again later."


def get_vies_adapter() -> SourceAdapter:
    """FastAPI dependency.

    VIES_BASE_URL can point to a stub for staging/load tests; VIES_ADAPTER=fake-...
    uses a fake without any network (see app/adapters/fake.py).
    """
    return with_fake_from_env(
        ViesAdapter(os.environ.get("VIES_BASE_URL") or DEFAULT_BASE_URL)
    )
