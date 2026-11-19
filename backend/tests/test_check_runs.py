"""Check runs (S5.1, T5.1.1): a run and its results are stored together."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.base import CheckStatus, SourceResult
from app.checks.runs import (
    COMPLETE,
    INCOMPLETE,
    RUNNING,
    final_status,
    finish_run,
    start_run,
)
from app.db.models import CheckResult, CheckRun, Organization, Partner

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
SOURCES = ["VIES", "BMF", "HFU"]


def answer(source: str, status: CheckStatus = CheckStatus.OK) -> SourceResult:
    return SourceResult(source, status, f"{source} says {status}", NOW, None, {"s": 1})


def make_partner(db: Session) -> Partner:
    organization = Organization(name="Run test organisation")
    db.add(organization)
    db.flush()
    partner = Partner(organization_id=organization.id, vat_number="ATU33864707")
    db.add(partner)
    db.flush()
    return partner


def new_run(db: Session, partner: Partner, sources: list[str] = SOURCES) -> CheckRun:
    run = start_run(
        db,
        organization_id=partner.organization_id,
        partner_id=partner.id,
        sources=sources,
        started_by="user-123",
    )
    db.commit()
    return run


def results_of(db: Session, run: CheckRun) -> list[CheckResult]:
    return list(db.scalars(select(CheckResult).where(CheckResult.run_id == run.id)))


def test_a_new_run_is_running_with_its_sources(db: Session) -> None:
    partner = make_partner(db)

    run = new_run(db, partner)

    stored = db.get(CheckRun, run.id)
    assert stored is not None
    assert stored.status == RUNNING
    assert stored.sources == SOURCES
    assert stored.started_by == "user-123"
    assert stored.started_at is not None
    assert stored.finished_at is None
    assert results_of(db, run) == []


def test_duplicate_sources_are_asked_once(db: Session) -> None:
    partner = make_partner(db)

    run = new_run(db, partner, ["VIES", "BMF", "VIES"])

    assert run.sources == ["VIES", "BMF"]


def test_final_status_rules() -> None:
    assert final_status(["VIES"], [answer("VIES", CheckStatus.FINDING)]) == COMPLETE
    assert final_status(["VIES"], [answer("VIES", CheckStatus.REVIEW)]) == COMPLETE
    assert final_status(["VIES"], [answer("VIES", CheckStatus.ERROR)]) == INCOMPLETE
    assert final_status(["VIES", "BMF"], [answer("VIES")]) == INCOMPLETE


def test_a_run_needs_at_least_one_source(db: Session) -> None:
    partner = make_partner(db)

    with pytest.raises(ValueError):
        start_run(
            db,
            organization_id=partner.organization_id,
            partner_id=partner.id,
            sources=[],
            started_by=None,
        )


def test_all_answers_make_the_run_complete_with_its_results(db: Session) -> None:
    partner = make_partner(db)
    run = new_run(db, partner)

    finish_run(
        db,
        run,
        [answer("VIES"), answer("BMF", CheckStatus.FINDING), answer("HFU")],
        now=NOW,
    )

    assert run.status == COMPLETE
    assert run.finished_at == NOW
    results = results_of(db, run)
    assert sorted(r.source for r in results) == sorted(SOURCES)
    assert all(r.partner_id == partner.id for r in results)
    bmf = next(r for r in results if r.source == "BMF")
    assert bmf.status == "FINDING"
    assert bmf.explanation == "BMF says FINDING"
    assert bmf.raw_response == {"s": 1}


def test_an_error_makes_the_run_incomplete(db: Session) -> None:
    partner = make_partner(db)
    run = new_run(db, partner)

    finish_run(
        db, run, [answer("VIES"), answer("BMF"), answer("HFU", CheckStatus.ERROR)]
    )

    assert run.status == INCOMPLETE
    # The ERROR is stored too: it is evidence that the source could not be asked.
    assert len(results_of(db, run)) == 3


def test_a_missing_answer_makes_the_run_incomplete(db: Session) -> None:
    partner = make_partner(db)
    run = new_run(db, partner)

    finish_run(db, run, [answer("VIES"), answer("BMF")])

    assert run.status == INCOMPLETE
    assert len(results_of(db, run)) == 2


def test_not_applicable_does_not_make_the_run_incomplete(db: Session) -> None:
    partner = make_partner(db)
    run = new_run(db, partner, ["VIES", "GISA"])

    finish_run(db, run, [answer("VIES"), answer("GISA", CheckStatus.NOT_APPLICABLE)])

    assert run.status == COMPLETE


def test_answers_of_other_sources_are_ignored(db: Session) -> None:
    partner = make_partner(db)
    run = new_run(db, partner, ["VIES"])

    finish_run(db, run, [answer("VIES"), answer("BMF")])

    assert [r.source for r in results_of(db, run)] == ["VIES"]


def test_a_finished_run_cannot_be_finished_again(db: Session) -> None:
    partner = make_partner(db)
    run = new_run(db, partner, ["VIES"])
    finish_run(db, run, [answer("VIES")])

    with pytest.raises(ValueError):
        finish_run(db, run, [answer("VIES", CheckStatus.ERROR)])

    assert run.status == COMPLETE
    assert len(results_of(db, run)) == 1


def test_run_and_results_are_saved_together_or_not_at_all(db: Session) -> None:
    partner = make_partner(db)
    run = new_run(db, partner, ["VIES", "BMF"])
    # A status the database refuses makes the second insert fail.
    broken = SourceResult("BMF", CheckStatus.OK, "", NOW, None, {})
    object.__setattr__(broken, "status", type("Bad", (), {"value": "NOPE"})())

    with pytest.raises(IntegrityError):
        finish_run(db, run, [answer("VIES"), broken])

    stored = db.get(CheckRun, run.id)
    assert stored is not None
    assert stored.status == RUNNING
    assert stored.finished_at is None
    assert results_of(db, run) == []


def test_old_results_without_a_run_still_work(db: Session) -> None:
    partner = make_partner(db)
    db.add(
        CheckResult(partner_id=partner.id, source="VIES", status="OK", raw_response={})
    )
    db.commit()

    result = db.scalar(select(CheckResult).where(CheckResult.partner_id == partner.id))
    assert result is not None
    assert result.run_id is None
