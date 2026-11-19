"""Review fixes for check runs: results one by one, BMF after VIES, one run at a time."""

import time
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.base import CheckStatus, CheckSubject, SourceAdapter, SourceResult
from app.checks.executor import ask_all
from app.checks.runs import COMPLETE, RUNNING, finish_run, record_result, start_run
from app.db.models import CheckRun, Organization, Partner

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


class Stub(SourceAdapter):
    """Answers after `delay` seconds and remembers what it was asked."""

    def __init__(
        self,
        source: str,
        *,
        delay: float = 0,
        status: CheckStatus = CheckStatus.OK,
        raw: dict | None = None,
    ) -> None:
        self.source = source
        super().__init__()
        self.delay = delay
        self.status = status
        self.raw = raw or {}
        self.asked: list[CheckSubject] = []

    def check(self, subject: CheckSubject) -> SourceResult:
        self.asked.append(subject)
        time.sleep(self.delay)
        return SourceResult(
            self.source, self.status, "", datetime.now(UTC), None, self.raw
        )

    def query(self, subject, timeout):  # pragma: no cover - not used
        return {}

    def interpret(self, raw):  # pragma: no cover - not used
        raise NotImplementedError

    def describe(self, status, raw):  # pragma: no cover - not used
        return ""

    def sample_answer(self, scenario, subject):  # pragma: no cover - not used
        return {}


def answer(source: str) -> SourceResult:
    return SourceResult(source, CheckStatus.OK, "", NOW, None, {})


# --- 1. results are stored one by one ------------------------------------------


def test_each_answer_is_reported_as_soon_as_it_is_there() -> None:
    started = time.monotonic()
    seen: dict[str, float] = {}

    ask_all(
        CheckSubject(vat_number="ATU12345678"),
        [Stub("VIES"), Stub("HFU", delay=1)],
        ["VIES", "HFU"],
        deadline=5,
        on_result=lambda r: seen.setdefault(r.source, time.monotonic() - started),
    )

    assert seen["VIES"] < 0.5
    assert seen["HFU"] >= 1


def make_partner(db: Session, **fields: str) -> Partner:
    organization = Organization(name="Progress test organisation")
    db.add(organization)
    db.flush()
    partner = Partner(
        organization_id=organization.id, vat_number="ATU12345678", **fields
    )
    db.add(partner)
    db.flush()
    return partner


def test_a_stored_answer_is_visible_while_the_run_is_still_running(
    db: Session,
) -> None:
    partner = make_partner(db)
    run = start_run(
        db,
        organization_id=partner.organization_id,
        partner_id=partner.id,
        sources=["VIES", "BMF", "HFU"],
        started_by=None,
    )
    db.commit()

    assert record_result(db, run, answer("VIES")) is True

    assert run.status == RUNNING
    assert len(db.get(CheckRun, run.id).sources) == 3  # type: ignore[union-attr]

    # finish_run keeps the stored answer and adds the others.
    finish_run(db, run, [answer("VIES"), answer("BMF"), answer("HFU")])
    assert run.status == COMPLETE


def test_an_answer_is_not_stored_twice_or_after_the_run_ended(db: Session) -> None:
    partner = make_partner(db)
    run = start_run(
        db,
        organization_id=partner.organization_id,
        partner_id=partner.id,
        sources=["VIES"],
        started_by=None,
    )
    db.commit()

    assert record_result(db, run, answer("VIES")) is True
    assert record_result(db, run, answer("VIES")) is False
    assert record_result(db, run, answer("GISA")) is False
    finish_run(db, run, [])
    assert record_result(db, run, answer("VIES")) is False


def test_the_api_shows_results_before_the_run_is_finished(
    client: TestClient, db: Session
) -> None:
    created = client.post("/api/v1/partners", json={"vat_number": "ATU12345678"})
    partner = db.get(Partner, uuid.UUID(created.json()["id"]))
    assert partner is not None
    run = start_run(
        db,
        organization_id=partner.organization_id,
        partner_id=partner.id,
        sources=["VIES", "BMF", "HFU"],
        started_by=None,
    )
    db.commit()
    record_result(db, run, answer("VIES"))

    body = client.get(f"/api/v1/runs/{run.id}").json()

    assert body["status"] == RUNNING
    assert [r["source"] for r in body["results"]] == ["VIES"]


# --- 2. BMF gets the company name from VIES in the same run ----------------------


def test_bmf_is_asked_with_the_name_vies_just_returned() -> None:
    vies = Stub("VIES", delay=0.2, raw={"isValid": True, "name": "Muster Bau GmbH"})
    bmf = Stub("BMF")

    ask_all(
        CheckSubject(vat_number="ATU12345678"),
        [vies, bmf, Stub("HFU")],
        ["VIES", "BMF", "HFU"],
        deadline=5,
    )

    assert [s.name for s in bmf.asked] == ["Muster Bau GmbH"]


def test_bmf_keeps_the_known_name_when_vies_has_none() -> None:
    vies = Stub("VIES", status=CheckStatus.ERROR, raw={"error": "MS_UNAVAILABLE"})
    bmf = Stub("BMF")

    ask_all(
        CheckSubject(vat_number="ATU12345678", name="Name the user typed"),
        [vies, bmf],
        ["VIES", "BMF"],
        deadline=5,
    )

    assert [s.name for s in bmf.asked] == ["Name the user typed"]


def test_fake_vies_names_are_never_used_for_bmf() -> None:
    vies = Stub("VIES", raw={"isValid": True, "name": "Fake GmbH", "fake": True})
    bmf = Stub("BMF")

    ask_all(CheckSubject(vat_number="ATU12345678"), [vies, bmf], ["VIES", "BMF"], 5)

    assert [s.name for s in bmf.asked] == [None]


def test_bmf_is_still_asked_when_vies_is_very_slow() -> None:
    vies = Stub("VIES", delay=3)
    bmf = Stub("BMF")
    started = time.monotonic()

    results = ask_all(
        CheckSubject(vat_number="ATU12345678"), [vies, bmf], ["VIES", "BMF"], 1.0
    )

    by_source = {r.source: r for r in results}
    assert by_source["BMF"].status == CheckStatus.OK
    assert by_source["VIES"].status == CheckStatus.ERROR
    assert time.monotonic() - started < 2


def test_without_vat_number_bmf_is_asked_at_once() -> None:
    bmf = Stub("BMF")

    results = ask_all(
        CheckSubject(vat_number=None, register_number="123456a"),
        [Stub("VIES"), bmf],
        ["VIES", "BMF"],
        5,
    )

    assert {r.source: r.status for r in results} == {
        "VIES": CheckStatus.NOT_APPLICABLE,
        "BMF": CheckStatus.OK,
    }
    assert len(bmf.asked) == 1


# --- 3. one run per partner at a time ------------------------------------------


def runs_of(db: Session, partner_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count())
        .select_from(CheckRun)
        .where(CheckRun.partner_id == partner_id)
    )


def test_starting_again_while_a_run_goes_on_returns_that_run(
    client: TestClient, db: Session
) -> None:
    created = client.post("/api/v1/partners", json={"vat_number": "ATU12345678"})
    partner = db.get(Partner, uuid.UUID(created.json()["id"]))
    assert partner is not None
    running = CheckRun(
        organization_id=partner.organization_id,
        partner_id=partner.id,
        status=RUNNING,
        sources=["VIES", "BMF", "HFU"],
    )
    db.add(running)
    db.commit()

    response = client.post(f"/api/v1/partners/{partner.id}/runs")

    assert response.status_code == 202
    assert response.json()["id"] == str(running.id)
    assert runs_of(db, partner.id) == 1


def test_an_interrupted_run_does_not_block_a_new_one(
    client: TestClient, db: Session
) -> None:
    created = client.post("/api/v1/partners", json={"vat_number": "ATU12345678"})
    partner = db.get(Partner, uuid.UUID(created.json()["id"]))
    assert partner is not None
    stuck = CheckRun(
        organization_id=partner.organization_id,
        partner_id=partner.id,
        status=RUNNING,
        sources=["VIES"],
        started_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    db.add(stuck)
    db.commit()

    response = client.post(f"/api/v1/partners/{partner.id}/runs")

    assert response.status_code == 202
    assert response.json()["id"] != str(stuck.id)
    db.refresh(stuck)
    assert stuck.status == "incomplete"
    assert runs_of(db, partner.id) == 2
