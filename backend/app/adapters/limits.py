"""Time limits and retries, shared by all source adapters.

Defaults from docs/architecture.md: 8 s per call, max. 2 retries, 30 s in total.
They can be changed without code changes through environment variables:

    SOURCE_TIMEOUT_SECONDS, SOURCE_MAX_RETRIES, SOURCE_DEADLINE_SECONDS   (all sources)
    VIES_TIMEOUT_SECONDS, VIES_MAX_RETRIES, VIES_DEADLINE_SECONDS         (one source)

The per-source value wins over the general one. Unreadable values are ignored
(with a warning), so a typo never stops the API from starting.
"""

import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 8.0
MAX_RETRIES = 2
DEADLINE_SECONDS = 30.0
RETRY_DELAY_SECONDS = 0.5
# Do not start another attempt when less time than this is left.
MIN_ATTEMPT_SECONDS = 1.0

T = TypeVar("T")


@dataclass(frozen=True)
class Limits:
    timeout: float = TIMEOUT_SECONDS
    max_retries: int = MAX_RETRIES
    deadline: float = DEADLINE_SECONDS
    retry_delay: float = RETRY_DELAY_SECONDS

    @classmethod
    def from_env(
        cls, source: str, environ: Mapping[str, str] | None = None
    ) -> "Limits":
        env = os.environ if environ is None else environ
        prefixes = (f"{source.upper()}_", "SOURCE_")
        return cls(
            timeout=_read(env, prefixes, "TIMEOUT_SECONDS", float, TIMEOUT_SECONDS),
            max_retries=_read(env, prefixes, "MAX_RETRIES", int, MAX_RETRIES),
            deadline=_read(env, prefixes, "DEADLINE_SECONDS", float, DEADLINE_SECONDS),
        )


def _read(
    env: Mapping[str, str],
    prefixes: tuple[str, ...],
    name: str,
    parse: Callable[[str], T],
    default: T,
) -> T:
    for prefix in prefixes:
        raw = env.get(prefix + name, "").strip()
        if not raw:
            continue
        try:
            value = parse(raw)
            if value >= 0:  # type: ignore[operator]  (T is int or float)
                return value
        except ValueError:
            pass
        logger.warning("Ignoring %s%s=%r (not a number >= 0)", prefix, name, raw)
    return default


@dataclass(frozen=True)
class Attempt(Generic[T]):
    """The outcome of one call, and whether asking again might help."""

    result: T
    try_again: bool


def run_with_limits(
    ask: Callable[[float], Attempt[T]],
    limits: Limits,
    *,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> T:
    """Call `ask(timeout)` until it gives a final answer, retries run out or time is up.

    Retries wait a little longer each time (0.5 s, 1 s, ...). The last result is
    returned as it is, so an adapter decides what "no answer" looks like.
    """
    started = clock()
    attempt = 0
    while True:
        remaining = limits.deadline - (clock() - started)
        outcome = ask(max(0.0, min(limits.timeout, remaining)))
        if not outcome.try_again or attempt >= limits.max_retries:
            return outcome.result
        delay = limits.retry_delay * (attempt + 1)
        time_left = limits.deadline - (clock() - started) - delay
        if time_left < MIN_ATTEMPT_SECONDS:
            # Not enough time left for another useful attempt.
            return outcome.result
        sleep(delay)
        attempt += 1
