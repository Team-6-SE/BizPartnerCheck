"""One interface and one result format for all external sources (S4.1).

Every source (VIES, BMF, HFU, Firmenbuch, GISA) is an adapter. An adapter only:

- `query`:     asks the source once and returns its answer as a dict (the raw answer),
- `interpret`: turns that raw answer into a status, and says if asking again could help,
- `describe`:  explains a status in one sentence for people,
- `sample_answer`: gives a typical answer for the fake version (tests, staging).

Time limits, retries, "no answer in time" and "not reachable" are handled here, the
same way for every source. Anything unclear is ERROR, never OK.

Details: docs/source-adapters.md
"""

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import httpx2 as httpx

from app.adapters.limits import Attempt, Limits, run_with_limits

logger = logging.getLogger(__name__)

# Our own error codes for problems before the source gave a usable answer.
NO_ANSWER_IN_TIME = "NO_ANSWER_IN_TIME"
NOT_REACHABLE = "NOT_REACHABLE"
BAD_RESPONSE = "BAD_RESPONSE"
# The adapter itself failed (a bug or an answer it did not expect).
ADAPTER_FAILED = "ADAPTER_FAILED"

FALLBACK_EXPLANATION = (
    "The source could not be checked. The result was not confirmed. "
    "Please try again later."
)


class CheckStatus(StrEnum):
    """The same statuses for every source, so the rules never need source-specific code."""

    # The source confirms: nothing against the partner (e.g. VAT number valid).
    OK = "OK"
    # The source reports a problem (e.g. VAT number invalid, partner on a blacklist).
    FINDING = "FINDING"
    # Something may be wrong and a person must look (e.g. same name, other number).
    REVIEW = "REVIEW"
    # The source does not cover this partner (e.g. Firmenbuch for a foreign company).
    NOT_APPLICABLE = "NOT_APPLICABLE"
    # The source could not be asked or gave no clear answer. Never counts as OK.
    ERROR = "ERROR"


class Scenario(StrEnum):
    """Answers a fake adapter can give (see app/adapters/fake.py)."""

    OK = "ok"
    FINDING = "finding"
    TIMEOUT = "timeout"
    MALFORMED = "malformed"


@dataclass(frozen=True)
class CheckSubject:
    """What we know about the partner; each source uses what it needs."""

    # Missing for partners added by company register number only (S3.1); sources
    # that need it (VIES) are not asked for such partners.
    vat_number: str | None
    name: str | None = None
    register_number: str | None = None
    requester_vat: str | None = None

@dataclass(frozen=True)
class SourceResult:
    """The common result of one check against one source."""

    source: str
    status: CheckStatus
    # One sentence for people: what the result means and what to do.
    explanation: str
    # When we asked the source.
    retrieved_at: datetime
    # How current the source's data was. None for live sources (data is as of
    # retrieved_at); set for imported lists (time of the last import).
    data_as_of: datetime | None
    # The answer of the source exactly as received, or what went wrong. Stored for
    # every result (OK, FINDING, REVIEW and ERROR) as evidence.
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def data_age(self) -> timedelta:
        if self.data_as_of is None:
            return timedelta(0)
        return self.retrieved_at - self.data_as_of


@dataclass(frozen=True)
class Interpretation:
    status: CheckStatus
    try_again: bool = False


class SourceAdapter(ABC):
    """Base class of all adapters. Subclasses implement the four methods below."""

    #: Short name stored with every result, e.g. "VIES".
    source: str

    def __init__(
        self,
        *,
        limits: Limits | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.limits = limits or Limits.from_env(self.source)
        # Tests replace the clocks, so retries and time limits run without waiting.
        self._clock = clock
        self._sleep = sleep
        self._now = now

    # --- implemented by each source -------------------------------------------

    @abstractmethod
    def query(self, subject: CheckSubject, timeout: float) -> dict[str, Any]:
        """Ask the source once. May raise httpx errors (timeouts, connection problems)."""

    @abstractmethod
    def interpret(self, raw: dict[str, Any]) -> Interpretation:
        """Map the raw answer to a status. Anything unclear must be ERROR."""

    @abstractmethod
    def describe(self, status: CheckStatus, raw: dict[str, Any]) -> str:
        """One sentence for people: what the result means and what to do."""

    @abstractmethod
    def sample_answer(self, scenario: Scenario, subject: CheckSubject) -> dict[str, Any]:
        """A typical raw answer for Scenario.OK and Scenario.FINDING (fake adapters)."""

    def data_as_of(self, raw: dict[str, Any]) -> datetime | None:
        """How current the data is. Live sources keep the default (None)."""
        return None

    # --- the same for every source --------------------------------------------

    def check(self, subject: CheckSubject) -> SourceResult:
        """Ask the source within the time limits and return the common result."""
        raw, status = run_with_limits(
            lambda timeout: self._attempt(subject, timeout),
            self.limits,
            clock=self._clock,
            sleep=self._sleep,
        )
        return SourceResult(
            source=self.source,
            status=status,
            explanation=self._explain(status, raw),
            retrieved_at=self._now(),
            data_as_of=self._data_as_of(raw),
            raw=raw,
        )

    def _explain(self, status: CheckStatus, raw: dict[str, Any]) -> str:
        try:
            return self.describe(status, raw)
        except Exception:
            logger.exception("%s adapter: describe() failed", self.source)
            return FALLBACK_EXPLANATION

    def _data_as_of(self, raw: dict[str, Any]) -> datetime | None:
        try:
            return self.data_as_of(raw)
        except Exception:
            logger.exception("%s adapter: data_as_of() failed", self.source)
            return None

    def _attempt(
        self, subject: CheckSubject, timeout: float
    ) -> Attempt[tuple[dict[str, Any], CheckStatus]]:
        try:
            raw = self.query(subject, timeout)
        except httpx.TimeoutException:
            raw = {
                "error": NO_ANSWER_IN_TIME,
                "message": f"No answer within {round(timeout, 1):g} s.",
            }
            return Attempt((raw, CheckStatus.ERROR), try_again=True)
        except httpx.HTTPError as exc:
            raw = {"error": NOT_REACHABLE, "message": type(exc).__name__}
            return Attempt((raw, CheckStatus.ERROR), try_again=True)
        except Exception as exc:
            return self._failed("query", exc, answer=None)

        if not isinstance(raw, dict):
            raw = {"error": BAD_RESPONSE, "message": repr(raw)[:500]}
            return Attempt((raw, CheckStatus.ERROR), try_again=False)

        try:
            interpretation = self.interpret(raw)
        except Exception as exc:
            return self._failed("interpret", exc, answer=raw)
        return Attempt((raw, interpretation.status), interpretation.try_again)

    def _failed(
        self, step: str, exc: Exception, answer: dict[str, Any] | None
    ) -> Attempt[tuple[dict[str, Any], CheckStatus]]:
        """Anything unclear is ERROR: an adapter bug must not break the request."""
        logger.exception("%s adapter: %s() failed", self.source, step)
        raw: dict[str, Any] = {
            "error": ADAPTER_FAILED,
            "message": f"{step}: {type(exc).__name__}",
        }
        if answer is not None:
            # Keep what the source said, as evidence and for finding the bug.
            raw["answer"] = answer
        # A bug will not go away when asked again.
        return Attempt((raw, CheckStatus.ERROR), try_again=False)
