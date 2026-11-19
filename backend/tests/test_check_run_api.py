"""API for check runs (S5.1, T5.1.3): start at once, then poll for the results.

In tests the run's background task finishes before client.post() returns, so the
next GET already sees the final status.
"""

import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.adapters.base import CheckStatus, CheckSubject, SourceAdapter, SourceResult
from app.bmf.importer import run_import
from app.checks.executor import ask_all
from app.db.models import CheckRun, Organization, Partner

SAMPLE = Path(__file__).parent / "fixtures" / "bmf_feed_sample.xml"
NOT_ON_BMF_LIST = "ATU12345678"


def import_bmf_list(db: Session) -> None:
    imported = datetime.now(UTC) - timedelta(hours=1)
    record = run_import(
        db, SAMPLE.read_bytes(), trigger="schedule", now=lambda: imported
    )
    assert record.status == "SUCCESS"


def set_organization_vat(client: TestClient, admin_token: str) -> None:
    response = client.put(
        "/api/v1/organization",
        json={"vat_number": "ATU99999999"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text


def add_partner(client: TestClient, **fields: str) -> dict:
    body = fields or {"vat_number": NOT_ON_BMF_LIST}
    response = client.post("/api/v1/partners", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def start(client: TestClient, partner_id: str):
    return client.post(f"/api/v1/partners/{partner_id}/runs")


def get_run(client: TestClient, run_id: str) -> dict:
    response = client.get(f"/api/v1/runs/{run_id}")
    assert response.status_code == 200, response.text
    return response.json()


def statuses(run: dict) -> dict[str, str]:
    return {result["source"]: result["status"] for result in run["results"]}


def test_start_returns_202_at_once_with_a_running_run(client: TestClient) -> None:
    partner = add_partner(client)

    response = start(client, partner["id"])

    assert response.status_code == 202
    run = response.json()
    assert run["status"] == "running"
    assert run["partner_id"] == partner["id"]
    assert run["sources"] == ["VIES", "BMF", "HFU"]
    assert run["results"] == []
    assert run["finished_at"] is None


def test_complete_when_every_source_answers(
    client: TestClient, db: Session, admin_token: str
) -> None:
    import_bmf_list(db)
    set_organization_vat(client, admin_token)
    partner = add_partner(client)

    run = get_run(client, start(client, partner["id"]).json()["id"])

    assert run["status"] == "complete"
    assert run["finished_at"] is not None
    assert [r["source"] for r in run["results"]] == ["VIES", "BMF", "HFU"]
    assert statuses(run) == {"VIES": "OK", "BMF": "OK", "HFU": "OK"}
    vies = run["results"][0]
    assert vies["company_name"] == "Muster Bau GmbH"
    assert vies["message"]


def test_a_failing_source_makes_the_run_incomplete_but_the_others_finish(
    client: TestClient, db: Session, admin_token: str, fake_vies
) -> None:
    import_bmf_list(db)
    set_organization_vat(client, admin_token)
    fake_vies.answer = {"error": "MS_UNAVAILABLE"}
    partner = add_partner(client)

    run = get_run(client, start(client, partner["id"]).json()["id"])

    assert run["status"] == "incomplete"
    assert statuses(run) == {"VIES": "ERROR", "BMF": "OK", "HFU": "OK"}


def test_without_organisation_vat_hfu_is_error_and_the_run_incomplete(
    client: TestClient, db: Session
) -> None:
    import_bmf_list(db)
    partner = add_partner(client)

    run = get_run(client, start(client, partner["id"]).json()["id"])

    assert run["status"] == "incomplete"
    assert statuses(run)["HFU"] == "ERROR"


def test_partner_without_vat_number_gets_not_applicable(
    client: TestClient, db: Session, fake_vies, fake_hfu
) -> None:
    import_bmf_list(db)
    partner = add_partner(client, company_register_number="987654z")

    run = get_run(client, start(client, partner["id"]).json()["id"])

    assert statuses(run) == {
        "VIES": "NOT_APPLICABLE",
        "BMF": "OK",
        "HFU": "NOT_APPLICABLE",
    }
    assert run["status"] == "complete"
    assert fake_vies.checked == []
    assert fake_hfu.checked == []


def test_run_results_also_count_as_latest_partner_results(
    client: TestClient, db: Session, admin_token: str
) -> None:
    import_bmf_list(db)
    set_organization_vat(client, admin_token)
    partner = add_partner(client)
    start(client, partner["id"])

    listed = client.get("/api/v1/partners").json()["items"][0]

    assert listed["latest_vies_check"]["status"] == "OK"
    assert listed["latest_bmf_check"]["status"] == "OK"
    assert listed["latest_hfu_check"]["status"] == "OK"


def test_who_started_the_run_is_stored(client: TestClient, db: Session) -> None:
    partner = add_partner(client)

    run_id = start(client, partner["id"]).json()["id"]

    run = db.get(CheckRun, uuid.UUID(run_id))
    assert run is not None
    assert run.started_by == "user-1"


def test_archived_partner_cannot_be_checked(client: TestClient) -> None:
    partner = add_partner(client)
    client.patch(f"/api/v1/partners/{partner['id']}/archive")

    response = start(client, partner["id"])

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "partner_archived"


def test_unknown_partner_gives_404(client: TestClient) -> None:
    response = start(client, str(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "partner_not_found"


def test_unknown_run_gives_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/runs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "run_not_found"


def test_runs_of_other_organisations_are_not_visible(
    client: TestClient, db: Session
) -> None:
    other = Organization(name="Other organisation")
    db.add(other)
    db.flush()
    partner = Partner(organization_id=other.id, vat_number=NOT_ON_BMF_LIST)
    db.add(partner)
    db.flush()
    run = CheckRun(
        organization_id=other.id,
        partner_id=partner.id,
        status="running",
        sources=["VIES"],
    )
    db.add(run)
    db.commit()

    assert client.get(f"/api/v1/runs/{run.id}").status_code == 404
    assert start(client, str(partner.id)).status_code == 404


def test_partners_of_other_organisations_cannot_be_started(
    client: TestClient, db: Session
) -> None:
    other = Organization(name="Other organisation")
    db.add(other)
    db.flush()
    partner = Partner(organization_id=other.id, vat_number=NOT_ON_BMF_LIST)
    db.add(partner)
    db.commit()

    assert start(client, str(partner.id)).status_code == 404


class SlowAdapter(SourceAdapter):
    source = "SLOW"

    def check(self, subject: CheckSubject) -> SourceResult:
        time.sleep(1)
        return SourceResult("SLOW", CheckStatus.OK, "", datetime.now(UTC), None, {})

    def query(self, subject, timeout):  # pragma: no cover - not used
        return {}

    def interpret(self, raw):  # pragma: no cover - not used
        raise NotImplementedError

    def describe(self, status, raw):  # pragma: no cover - not used
        return ""

    def sample_answer(self, scenario, subject):  # pragma: no cover - not used
        return {}


class QuickAdapter(SlowAdapter):
    source = "QUICK"

    def check(self, subject: CheckSubject) -> SourceResult:
        return SourceResult("QUICK", CheckStatus.OK, "", datetime.now(UTC), None, {})


def test_a_source_that_is_too_late_becomes_error_and_the_others_finish() -> None:
    subject = CheckSubject(vat_number="ATU12345678")
    started = time.monotonic()

    results = ask_all(
        subject, [SlowAdapter(), QuickAdapter()], ["SLOW", "QUICK"], deadline=0.2
    )

    assert time.monotonic() - started < 0.9
    by_source = {r.source: r for r in results}
    assert by_source["QUICK"].status == CheckStatus.OK
    assert by_source["SLOW"].status == CheckStatus.ERROR
    assert "did not answer within 0.2 s" in by_source["SLOW"].explanation


def test_sources_are_asked_in_parallel() -> None:
    subject = CheckSubject(vat_number="ATU12345678")
    started = time.monotonic()

    results = ask_all(
        subject,
        [SlowAdapter(), SlowAdapter(), SlowAdapter()],
        ["A", "B", "C"],
        deadline=5,
    )

    # Three sources of 1 s each take about 1 s together, not 3 s.
    assert time.monotonic() - started < 2
    assert len(results) == 3
