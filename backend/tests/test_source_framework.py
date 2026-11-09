"""The common source adapter framework: result format, time limits, fakes (S4.1)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.adapters.base import (
    CheckStatus,
    CheckSubject,
    Interpretation,
    Scenario,
    SourceAdapter,
    SourceResult,
)
from app.adapters.fake import FakeAdapter, UnknownAdapterSetting, with_fake_from_env
from app.adapters.limits import Attempt, Limits, run_with_limits
from app.adapters.vies import ViesAdapter, get_vies_adapter

SUBJECT = CheckSubject(vat_number="ATU12345678")
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


class FakeClock:
    """Time that only moves when the code sleeps or a call "takes" time."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


# --- time limits and retries -------------------------------------------------


def asking(*outcomes: Attempt[str], clock: FakeClock, takes: float = 0.0):
    queue = list(outcomes)
    timeouts: list[float] = []

    def ask(timeout: float) -> Attempt[str]:
        timeouts.append(timeout)
        clock.now += takes
        return queue.pop(0)

    return ask, timeouts


def test_final_answer_is_not_asked_again() -> None:
    clock = FakeClock()
    ask, timeouts = asking(Attempt("answer", try_again=False), clock=clock)

    result = run_with_limits(ask, Limits(), clock=clock, sleep=clock.sleep)

    assert result == "answer"
    assert timeouts == [8.0]
    assert clock.sleeps == []


def test_temporary_problem_is_retried_twice_with_growing_pauses() -> None:
    clock = FakeClock()
    busy = Attempt("busy", try_again=True)
    ask, timeouts = asking(busy, busy, busy, busy, clock=clock)

    result = run_with_limits(ask, Limits(), clock=clock, sleep=clock.sleep)

    assert result == "busy"
    assert len(timeouts) == 3  # first try + 2 retries
    assert clock.sleeps == [0.5, 1.0]


def test_retry_stops_at_first_final_answer() -> None:
    clock = FakeClock()
    ask, timeouts = asking(
        Attempt("busy", try_again=True), Attempt("ok", try_again=False), clock=clock
    )

    assert run_with_limits(ask, Limits(), clock=clock, sleep=clock.sleep) == "ok"
    assert len(timeouts) == 2


def test_overall_limit_shortens_the_last_call_and_stops_retries() -> None:
    clock = FakeClock()
    slow = Attempt("slow", try_again=True)
    ask, timeouts = asking(slow, slow, slow, clock=clock, takes=12.0)

    run_with_limits(ask, Limits(), clock=clock, sleep=clock.sleep)

    # 0 s: 8 s allowed; 12.5 s: 8 s allowed; 25.5 s: only 4.5 s left of 30 s.
    assert timeouts == [8.0, 8.0, 4.5]


def test_no_retry_when_too_little_time_is_left() -> None:
    clock = FakeClock()
    slow = Attempt("slow", try_again=True)
    ask, timeouts = asking(slow, slow, clock=clock, takes=29.0)

    run_with_limits(ask, Limits(), clock=clock, sleep=clock.sleep)

    assert len(timeouts) == 1


# --- configuration without code changes --------------------------------------


def test_limits_default_to_the_architecture_values() -> None:
    assert Limits.from_env("VIES", {}) == Limits(8.0, 2, 30.0)


def test_limits_can_be_set_for_all_sources_and_per_source() -> None:
    env = {
        "SOURCE_TIMEOUT_SECONDS": "5",
        "SOURCE_MAX_RETRIES": "1",
        "VIES_TIMEOUT_SECONDS": "3.5",
        "BMF_DEADLINE_SECONDS": "60",
    }

    assert Limits.from_env("VIES", env) == Limits(timeout=3.5, max_retries=1)
    assert Limits.from_env("BMF", env) == Limits(5.0, 1, 60.0)


@pytest.mark.parametrize("value", ["abc", "-1", "1,5"])
def test_unreadable_limits_fall_back(value: str) -> None:
    env = {"VIES_TIMEOUT_SECONDS": value, "SOURCE_TIMEOUT_SECONDS": "6"}

    assert Limits.from_env("VIES", env).timeout == 6.0
    assert Limits.from_env("VIES", {"VIES_MAX_RETRIES": value}).max_retries == 2


# --- the common result -------------------------------------------------------


class ListSource(SourceAdapter):
    """A minimal adapter: what a new source has to implement."""

    source = "LIST"

    def __init__(self, answer: Any, imported_at: datetime | None = None) -> None:
        super().__init__(limits=Limits(), now=lambda: NOW, sleep=lambda _s: None)
        self.answer = answer
        self.imported_at = imported_at

    def query(self, subject: CheckSubject, timeout: float) -> dict[str, Any]:
        return self.answer

    def interpret(self, raw: dict[str, Any]) -> Interpretation:
        return Interpretation(
            {"listed": CheckStatus.FINDING, "clean": CheckStatus.OK}.get(
                raw.get("result"), CheckStatus.ERROR
            )
        )

    def describe(self, status: CheckStatus, raw: dict[str, Any]) -> str:
        return f"List says {status.value}."

    def sample_answer(self, scenario: Scenario, subject: CheckSubject) -> dict[str, Any]:
        return {"result": "listed" if scenario == Scenario.FINDING else "clean"}

    def data_as_of(self, raw: dict[str, Any]) -> datetime | None:
        return self.imported_at


@pytest.mark.parametrize(
    ("answer", "status"),
    [
        ({"result": "clean"}, CheckStatus.OK),
        ({"result": "listed"}, CheckStatus.FINDING),
        ({"result": "???"}, CheckStatus.ERROR),
    ],
)
def test_result_has_all_common_fields_and_keeps_the_raw_answer(
    answer: dict, status: CheckStatus
) -> None:
    result = ListSource(answer).check(SUBJECT)

    assert result.source == "LIST"
    assert result.status == status
    assert result.explanation == f"List says {status.value}."
    assert result.retrieved_at == NOW
    assert result.data_as_of is None
    assert result.data_age == timedelta(0)
    assert result.raw == answer  # stored for OK, FINDING and ERROR


def test_data_age_of_an_imported_list() -> None:
    imported = NOW - timedelta(hours=30)

    result = ListSource({"result": "clean"}, imported_at=imported).check(SUBJECT)

    assert result.data_as_of == imported
    assert result.data_age == timedelta(hours=30)


def test_answer_that_is_not_an_object_is_error() -> None:
    result = ListSource(["not", "a", "dict"]).check(SUBJECT)

    assert result.status == CheckStatus.ERROR
    assert result.raw["error"] == "BAD_RESPONSE"


def test_result_is_immutable() -> None:
    result = SourceResult("X", CheckStatus.OK, "", NOW, None, {})
    with pytest.raises(AttributeError):
        result.status = CheckStatus.FINDING  # type: ignore[misc]


# --- fake adapters -------------------------------------------------------------


def fake_vies(scenario: Scenario) -> FakeAdapter:
    real = ViesAdapter(limits=Limits(), sleep=lambda _s: None, now=lambda: NOW)
    return FakeAdapter(real, scenario)


def test_fake_ok_and_finding_use_the_real_interpretation() -> None:
    ok = fake_vies(Scenario.OK).check(SUBJECT)
    finding = fake_vies(Scenario.FINDING).check(SUBJECT)

    assert ok.status == CheckStatus.OK
    assert "valid" in ok.explanation
    assert finding.status == CheckStatus.FINDING
    assert "not valid" in finding.explanation


def test_fake_timeout_is_retried_and_gives_error() -> None:
    adapter = fake_vies(Scenario.TIMEOUT)

    result = adapter.check(SUBJECT)

    assert result.status == CheckStatus.ERROR
    assert result.raw["error"] == "NO_ANSWER_IN_TIME"
    assert "did not answer in time" in result.explanation
    assert len(adapter.queried) == 3


def test_fake_malformed_answer_gives_error_never_ok() -> None:
    result = fake_vies(Scenario.MALFORMED).check(SUBJECT)

    assert result.status == CheckStatus.ERROR
    assert "not confirmed" in result.explanation


def test_every_adapter_has_a_fake_version() -> None:
    """An adapter without sample answers for its fake cannot be created."""

    class NoFake(SourceAdapter):
        source = "NOFAKE"

        def query(self, subject, timeout):
            return {}

        def interpret(self, raw):
            return Interpretation(CheckStatus.ERROR)

        def describe(self, status, raw):
            return ""

    with pytest.raises(TypeError, match="sample_answer"):
        NoFake()  # type: ignore[abstract]


@pytest.mark.parametrize("setting", ["", "real", " REAL "])
def test_real_adapter_by_default(setting: str) -> None:
    real = ViesAdapter()

    assert with_fake_from_env(real, {"VIES_ADAPTER": setting}) is real


@pytest.mark.parametrize("scenario", list(Scenario))
def test_fake_selected_by_environment_variable(scenario: Scenario) -> None:
    adapter = with_fake_from_env(
        ViesAdapter(), {"VIES_ADAPTER": f"fake-{scenario.value}"}
    )

    assert isinstance(adapter, FakeAdapter)
    assert adapter.scenario == scenario
    assert adapter.source == "VIES"


@pytest.mark.parametrize("setting", ["fake", "fake-maybe", "mock"])
def test_unknown_setting_is_refused(setting: str) -> None:
    with pytest.raises(UnknownAdapterSetting, match="VIES_ADAPTER"):
        with_fake_from_env(ViesAdapter(), {"VIES_ADAPTER": setting})


def test_api_dependency_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIES_ADAPTER", "fake-finding")

    adapter = get_vies_adapter()

    assert isinstance(adapter, FakeAdapter)
    assert adapter.check(SUBJECT).status == CheckStatus.FINDING
