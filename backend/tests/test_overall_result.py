"""Overall traffic-light result (S5.2, T5.2.1 and T5.2.3). Pure rules, no database."""

import itertools

import pytest

from app.adapters.base import CheckStatus
from app.checks.overall import (
    DEFAULT_LEVELS,
    InvalidRules,
    Level,
    Rules,
    overall_result,
    sources_left_out,
)

OK = CheckStatus.OK
FINDING = CheckStatus.FINDING
REVIEW = CheckStatus.REVIEW
ERROR = CheckStatus.ERROR
NA = CheckStatus.NOT_APPLICABLE

SOURCES = ("VIES", "BMF", "HFU")
DEFAULT = Rules()


def level(**statuses: CheckStatus) -> Level:
    return overall_result(list(statuses), statuses, DEFAULT).level


def expected(statuses: tuple[CheckStatus, ...]) -> Level:
    """The documented rules, written out once more on their own."""
    if FINDING in statuses:
        return Level.RED
    if ERROR in statuses or REVIEW in statuses:
        return Level.YELLOW
    if all(status == NA for status in statuses):
        return Level.YELLOW  # nothing could be checked
    return Level.GREEN


# --- every combination of statuses (acceptance criterion 1) -----------------------


@pytest.mark.parametrize(
    "statuses", list(itertools.product(list(CheckStatus), repeat=len(SOURCES)))
)
def test_every_combination_follows_the_documented_rules(
    statuses: tuple[CheckStatus, ...],
) -> None:
    result = overall_result(SOURCES, dict(zip(SOURCES, statuses)), DEFAULT)

    assert result.level == expected(statuses)
    assert result.summary  # always explained
    assert [reason.source for reason in result.reasons] == list(SOURCES)


def test_all_ok_is_green() -> None:
    assert level(VIES=OK, BMF=OK, HFU=OK) == Level.GREEN


def test_one_finding_is_red_whatever_the_others_say() -> None:
    assert level(VIES=OK, BMF=FINDING, HFU=OK) == Level.RED
    assert level(VIES=ERROR, BMF=FINDING, HFU=REVIEW) == Level.RED


def test_an_error_is_yellow_not_green() -> None:
    assert level(VIES=OK, BMF=OK, HFU=ERROR) == Level.YELLOW


def test_a_source_without_any_result_is_yellow() -> None:
    result = overall_result(SOURCES, {"VIES": OK, "BMF": OK}, DEFAULT)

    assert result.level == Level.YELLOW
    assert result.reasons[2].status is None
    assert result.summary.startswith("The HFU list could not be checked")


def test_review_is_never_green() -> None:
    # A name-only BMF match must never look like a clean result.
    assert level(VIES=OK, BMF=REVIEW, HFU=OK) == Level.YELLOW


def test_not_applicable_sources_do_not_spoil_a_green_result() -> None:
    result = overall_result(SOURCES, {"VIES": NA, "BMF": OK, "HFU": NA}, DEFAULT)

    assert result.level == Level.GREEN
    assert "does not apply" not in result.summary  # two sources: "do not apply"
    assert "VIES and the HFU list do not apply" in result.summary


def test_nothing_applies_is_yellow_not_green() -> None:
    result = overall_result(SOURCES, {s: NA for s in SOURCES}, DEFAULT)

    assert result.level == Level.YELLOW
    assert "Nothing could be checked" in result.summary


def test_the_deciding_sources_are_the_ones_with_the_overall_level() -> None:
    result = overall_result(
        SOURCES, {"VIES": OK, "BMF": FINDING, "HFU": ERROR}, DEFAULT
    )

    assert [reason.source for reason in result.deciding] == ["BMF"]


# --- explanation texts (T5.2.3) ----------------------------------------------------


def test_red_names_the_source_and_also_says_what_is_missing() -> None:
    result = overall_result(
        SOURCES, {"VIES": OK, "BMF": FINDING, "HFU": ERROR}, DEFAULT
    )

    assert result.summary == (
        "A problem was found by the BMF list. The HFU list could not be checked, so "
        "the result is not complete. Please check again later."
    )


def test_yellow_for_an_error_says_the_result_is_not_complete() -> None:
    result = overall_result(SOURCES, {"VIES": ERROR, "BMF": OK, "HFU": OK}, DEFAULT)

    assert result.summary == (
        "VIES could not be checked, so the result is not complete. "
        "Please check again later."
    )


def test_yellow_for_a_review_asks_a_person_to_look() -> None:
    result = overall_result(SOURCES, {"VIES": OK, "BMF": REVIEW, "HFU": OK}, DEFAULT)

    assert result.summary == "The BMF list found something a person must review."


def test_green_names_every_source_that_was_asked() -> None:
    result = overall_result(
        ("VIES", "BMF", "HFU", "FIRMENBUCH", "GISA"),
        {"VIES": OK, "BMF": OK, "HFU": OK, "FIRMENBUCH": OK, "GISA": NA},
        DEFAULT,
    )

    assert result.summary == (
        "No problems were found by VIES, the BMF list, the HFU list and the Firmenbuch. "
        "GISA does not apply to this partner."
    )


def test_several_findings_are_all_named() -> None:
    result = overall_result(
        SOURCES, {"VIES": FINDING, "BMF": FINDING, "HFU": OK}, DEFAULT
    )

    assert result.summary == "A problem was found by VIES and the BMF list."


# --- configurable rules --------------------------------------------------------------


def test_default_rules_match_the_story() -> None:
    assert Rules.from_env({}).levels == DEFAULT_LEVELS


def test_a_level_can_be_changed_in_the_environment() -> None:
    rules = Rules.from_env({"OVERALL_LEVEL_REVIEW": "red"})

    result = overall_result(SOURCES, {"VIES": OK, "BMF": REVIEW, "HFU": OK}, rules)

    assert result.level == Level.RED
    assert "must review" in result.summary


def test_unusual_settings_are_still_explained() -> None:
    rules = Rules.from_env({"OVERALL_LEVEL_OK": "YELLOW"})

    result = overall_result(SOURCES, {s: OK for s in SOURCES}, rules)

    assert result.level == Level.YELLOW
    assert "set to yellow" in result.summary


@pytest.mark.parametrize("status", ["FINDING", "ERROR"])
def test_a_problem_or_missing_answer_can_never_be_green(status: str) -> None:
    with pytest.raises(InvalidRules, match="can never be GREEN"):
        Rules.from_env({f"OVERALL_LEVEL_{status}": "GREEN"})


def test_a_wrong_level_stops_with_a_clear_message() -> None:
    with pytest.raises(InvalidRules, match="OVERALL_LEVEL_REVIEW='orange'"):
        Rules.from_env({"OVERALL_LEVEL_REVIEW": "orange"})


def test_a_missing_source_is_yellow_even_when_errors_are_set_to_red() -> None:
    # No answer at all is "missing information", not a finding.
    rules = Rules.from_env({"OVERALL_LEVEL_ERROR": "RED"})

    result = overall_result(SOURCES, {"VIES": OK, "BMF": OK}, rules)

    assert result.level == Level.YELLOW


def test_a_run_without_sources_has_no_result() -> None:
    with pytest.raises(ValueError):
        overall_result([], {}, DEFAULT)


# --- sources that are not set up on the server (review follow-up) -------------------


def test_register_sources_left_out_only_matter_with_a_register_number() -> None:
    assert sources_left_out(SOURCES, has_register_number=True) == (
        "FIRMENBUCH",
        "GISA",
    )
    assert sources_left_out(SOURCES, has_register_number=False) == ()
    assert sources_left_out((*SOURCES, "FIRMENBUCH"), has_register_number=True) == (
        "GISA",
    )


def test_a_source_that_is_not_set_up_is_named_but_does_not_change_the_level() -> None:
    result = overall_result(
        SOURCES,
        {"VIES": OK, "BMF": OK, "HFU": OK},
        DEFAULT,
        not_checked=["FIRMENBUCH"],
    )

    assert result.level == Level.GREEN
    assert result.not_checked == ("FIRMENBUCH",)
    assert result.summary.endswith(
        "The Firmenbuch is not set up on this server, so it was not checked."
    )


def test_two_sources_not_set_up() -> None:
    result = overall_result(
        SOURCES,
        {"VIES": OK, "BMF": FINDING, "HFU": OK},
        DEFAULT,
        not_checked=["FIRMENBUCH", "GISA"],
    )

    assert result.level == Level.RED
    assert result.summary == (
        "A problem was found by the BMF list. The Firmenbuch and GISA are not set up "
        "on this server, so they were not checked."
    )
