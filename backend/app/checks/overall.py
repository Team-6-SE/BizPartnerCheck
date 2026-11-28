"""Overall traffic-light result of a check run (S5.2, T5.2.1 and T5.2.3).

Pure Python: no database and no web framework, so the rules are easy to test and are the
same for the result screen, the history and the PDF report.

The worst level of all sources wins:

    RED      a source found a problem (FINDING)
    YELLOW   the result is not confirmed: a source failed or gave no answer (ERROR),
             or a person must look at something (REVIEW)
    GREEN    otherwise: every source answered OK or does not apply to this partner

Two cases are YELLOW whatever the settings say, because "nothing was found" is not the
same as "nothing could be checked": a source without any result, and a run in which no
source applied to the partner at all.

The level of each status can be changed with OVERALL_LEVEL_<STATUS> (for example
OVERALL_LEVEL_REVIEW=RED). FINDING and ERROR can never be GREEN: a problem or missing
information must not look like a clean result. Risk hints (E8) are not check results and
never change the overall result.
"""

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from app.adapters.base import CheckStatus


class Level(StrEnum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


# The higher level wins.
SEVERITY = {Level.GREEN: 0, Level.YELLOW: 1, Level.RED: 2}

DEFAULT_LEVELS: Mapping[CheckStatus, Level] = {
    CheckStatus.OK: Level.GREEN,
    CheckStatus.NOT_APPLICABLE: Level.GREEN,
    CheckStatus.REVIEW: Level.YELLOW,
    CheckStatus.ERROR: Level.YELLOW,
    CheckStatus.FINDING: Level.RED,
}

# A problem or missing information must never look like a clean result.
NEVER_GREEN = (CheckStatus.FINDING, CheckStatus.ERROR)

ENV_PREFIX = "OVERALL_LEVEL_"

# How sources are named in the explanation texts.
SOURCE_NAMES = {
    "VIES": "VIES",
    "BMF": "the BMF list",
    "HFU": "the HFU list",
    "FIRMENBUCH": "the Firmenbuch",
    "GISA": "GISA",
}

# Shown with every overall result (T5.2.4); also for the PDF report (S6.3).
DISCLAIMER = (
    "This result is information only. It shows what the official sources said at the "
    "time of the check. The decision whether to work with this partner stays with you."
)


class InvalidRules(ValueError):
    """An OVERALL_LEVEL_* setting is wrong; the API does not start with it."""


@dataclass(frozen=True)
class Rules:
    """Which level each check status gives."""

    levels: Mapping[CheckStatus, Level] = field(
        default_factory=lambda: dict(DEFAULT_LEVELS)
    )

    def __post_init__(self) -> None:
        missing = [status.value for status in CheckStatus if status not in self.levels]
        if missing:
            raise InvalidRules(f"No level for {', '.join(missing)}.")
        for status in NEVER_GREEN:
            if self.levels[status] == Level.GREEN:
                raise InvalidRules(f"{status.value} can never be GREEN.")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Rules":
        """The default rules, changed by OVERALL_LEVEL_<STATUS>=GREEN|YELLOW|RED."""
        env = os.environ if environ is None else environ
        levels = dict(DEFAULT_LEVELS)
        for status in CheckStatus:
            name = f"{ENV_PREFIX}{status.value}"
            raw = env.get(name, "").strip()
            if not raw:
                continue
            try:
                levels[status] = Level(raw.upper())
            except ValueError:
                raise InvalidRules(
                    f"{name}={raw!r} is not a level: use GREEN, YELLOW or RED."
                ) from None
        return cls(levels)

    def level_of(self, status: CheckStatus) -> Level:
        return self.levels[status]


@dataclass(frozen=True)
class Reason:
    """One source of the run and the level its result gives."""

    source: str
    # None: the source gave no result at all (counts as YELLOW, like ERROR).
    status: CheckStatus | None
    level: Level


@dataclass(frozen=True)
class OverallResult:
    level: Level
    # One to three sentences for people (T5.2.3).
    summary: str
    # Every source of the run, in the run's order.
    reasons: tuple[Reason, ...]

    @property
    def deciding(self) -> tuple[Reason, ...]:
        """The sources that decided the level."""
        return tuple(reason for reason in self.reasons if reason.level == self.level)


def overall_result(
    sources: Iterable[str],
    statuses: Mapping[str, CheckStatus | str],
    rules: Rules | None = None,
) -> OverallResult:
    """The overall level of a finished run, with its explanation.

    `sources` are the run's sources in order; `statuses` maps a source to its status.
    A source missing from `statuses` gave no result.
    """
    rules = rules or Rules.from_env()
    reasons = tuple(_reason(source, statuses.get(source), rules) for source in sources)
    if not reasons:
        raise ValueError("A run without sources has no overall result.")
    nothing_applied = all(r.status == CheckStatus.NOT_APPLICABLE for r in reasons)
    if nothing_applied:
        reasons = tuple(Reason(r.source, r.status, Level.YELLOW) for r in reasons)
    level = max((reason.level for reason in reasons), key=SEVERITY.__getitem__)
    return OverallResult(
        level=level,
        summary=_summary(level, reasons, nothing_applied),
        reasons=reasons,
    )


def _reason(source: str, raw: CheckStatus | str | None, rules: Rules) -> Reason:
    if raw is None:
        return Reason(source, None, Level.YELLOW)
    status = CheckStatus(raw)
    return Reason(source, status, rules.level_of(status))


def source_name(source: str) -> str:
    return SOURCE_NAMES.get(source.upper(), source)


def _names(reasons: Iterable[Reason]) -> str:
    """'VIES', 'VIES and the BMF list', 'VIES, the BMF list and GISA'."""
    names = [source_name(reason.source) for reason in reasons]
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _start(text: str) -> str:
    return text[:1].upper() + text[1:]


def _summary(level: Level, reasons: tuple[Reason, ...], nothing_applied: bool) -> str:
    if nothing_applied:
        return (
            "Nothing could be checked: none of the sources applies to this partner. "
            "Add a VAT number or a company register number and check again."
        )
    if level == Level.GREEN:
        return _green_summary(reasons)

    sentences: list[str] = []
    found = [r for r in reasons if r.status == CheckStatus.FINDING]
    review = [
        r for r in reasons if r.status == CheckStatus.REVIEW and r.level != Level.GREEN
    ]
    failed = [r for r in reasons if r.status in (CheckStatus.ERROR, None)]
    if found:
        sentences.append(f"A problem was found by {_names(found)}.")
    if review:
        sentences.append(
            f"{_start(_names(review))} found something a person must review."
        )
    if failed:
        sentences.append(
            f"{_start(_names(failed))} could not be checked, so the result is not "
            "complete. Please check again later."
        )
    unusual = [
        r
        for r in reasons
        if r.level == level and r not in found and r not in review and r not in failed
    ]
    if unusual:
        # Only with changed settings, e.g. OVERALL_LEVEL_OK=YELLOW.
        sentences.append(
            f"{_start(_names(unusual))} gave a result that is set to "
            f"{level.value.lower()}."
        )
    return " ".join(sentences)


def _green_summary(reasons: tuple[Reason, ...]) -> str:
    checked = [r for r in reasons if r.status not in (CheckStatus.NOT_APPLICABLE, None)]
    not_applied = [r for r in reasons if r.status == CheckStatus.NOT_APPLICABLE]
    sentences = [f"No problems were found by {_names(checked)}."]
    if not_applied:
        verb = "does" if len(not_applied) == 1 else "do"
        sentences.append(
            f"{_start(_names(not_applied))} {verb} not apply to this partner."
        )
    return " ".join(sentences)
