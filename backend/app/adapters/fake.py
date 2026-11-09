"""Fake versions of the source adapters, for tests and staging (no internet needed).

A fake adapter replaces only the call to the source. The answer still goes through the
real adapter's `interpret` and `describe`, and through the shared time limits, so a fake
"timeout" behaves exactly like a real one (ERROR, retried, explained).

Choose a fake per source with an environment variable named after the source:

    VIES_ADAPTER=fake-ok          the source confirms (e.g. VAT number valid)
    VIES_ADAPTER=fake-finding     the source reports a problem
    VIES_ADAPTER=fake-timeout     the source does not answer in time
    VIES_ADAPTER=fake-malformed   the source answers something we cannot read

Empty or "real" uses the real source. The settings are checked when the API starts
(`check_adapter_settings`): an unknown value stops the start with an error, so a typo
on staging does not silently call the real service, and an active fake is logged.

Fake results are marked with "fake": true in the stored raw answer, so they can never
be mistaken for evidence from the real source.
"""

import dataclasses
import logging
import os
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

import httpx2 as httpx

from app.adapters.base import (
    CheckStatus,
    CheckSubject,
    Interpretation,
    Scenario,
    SourceAdapter,
    SourceResult,
)

logger = logging.getLogger(__name__)

FAKE_PREFIX = "fake-"
# Key added to the raw answer of every fake result.
FAKE_MARKER = "fake"

MALFORMED_ANSWER: dict[str, Any] = {"unexpected": "an answer in an unknown format"}


class FakeAdapter(SourceAdapter):
    def __init__(self, real: SourceAdapter, scenario: Scenario) -> None:
        self.source = real.source
        super().__init__(
            limits=real.limits, clock=real._clock, sleep=real._sleep, now=real._now
        )
        self.real = real
        self.scenario = scenario
        self.queried: list[CheckSubject] = []

    def check(self, subject: CheckSubject) -> SourceResult:
        result = super().check(subject)
        # Mark every fake result (also timeouts and errors) in the stored evidence.
        return dataclasses.replace(result, raw={**result.raw, FAKE_MARKER: True})

    def query(self, subject: CheckSubject, timeout: float) -> dict[str, Any]:
        self.queried.append(subject)
        if self.scenario == Scenario.TIMEOUT:
            raise httpx.ReadTimeout(f"fake {self.source}: no answer")
        if self.scenario == Scenario.MALFORMED:
            return dict(MALFORMED_ANSWER)
        return self.real.sample_answer(self.scenario, subject)

    def interpret(self, raw: dict[str, Any]) -> Interpretation:
        return self.real.interpret(raw)

    def describe(self, status: CheckStatus, raw: dict[str, Any]) -> str:
        return self.real.describe(status, raw)

    def sample_answer(self, scenario: Scenario, subject: CheckSubject) -> dict[str, Any]:
        return self.real.sample_answer(scenario, subject)

    def data_as_of(self, raw: dict[str, Any]) -> datetime | None:
        return self.real.data_as_of(raw)


class UnknownAdapterSetting(ValueError):
    pass


def adapter_setting(
    source: str, environ: Mapping[str, str] | None = None
) -> Scenario | None:
    """The fake scenario chosen in {SOURCE}_ADAPTER, or None for the real source."""
    env = os.environ if environ is None else environ
    name = f"{source.upper()}_ADAPTER"
    setting = env.get(name, "").strip().lower()
    if setting in ("", "real"):
        return None
    if setting.startswith(FAKE_PREFIX):
        try:
            return Scenario(setting.removeprefix(FAKE_PREFIX))
        except ValueError:
            pass
    choices = ", ".join(["real", *(FAKE_PREFIX + s.value for s in Scenario)])
    raise UnknownAdapterSetting(f"{name}={setting!r} is not known. Use one of: {choices}.")


def check_adapter_settings(
    sources: Iterable[str], environ: Mapping[str, str] | None = None
) -> None:
    """Run once at startup: stop on unknown values, warn about every active fake."""
    for source in sources:
        scenario = adapter_setting(source, environ)
        if scenario is not None:
            logger.warning(
                "%s: FAKE adapter active (%s_ADAPTER=fake-%s). Results are not real "
                "and are marked \"fake\": true.",
                source,
                source.upper(),
                scenario.value,
            )


def with_fake_from_env(
    real: SourceAdapter, environ: Mapping[str, str] | None = None
) -> SourceAdapter:
    """The real adapter, or its fake version when {SOURCE}_ADAPTER asks for one."""
    scenario = adapter_setting(real.source, environ)
    return real if scenario is None else FakeAdapter(real, scenario)
