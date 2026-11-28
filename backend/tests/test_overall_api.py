"""The overall result in the check-run API (S5.2): GET /runs/{id} gives `overall`."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.bmf.importer import run_import
from app.checks.overall import DISCLAIMER

SAMPLE = Path(__file__).parent / "fixtures" / "bmf_feed_sample.xml"
NOT_ON_BMF_LIST = "ATU12345678"
ON_BMF_LIST = "ATU11111111"  # "Muster Scheinbau GmbH" in the sample feed


def import_bmf_list(db: Session) -> None:
    imported = datetime.now(UTC) - timedelta(hours=1)
    assert (
        run_import(
            db, SAMPLE.read_bytes(), trigger="schedule", now=lambda: imported
        ).status
        == "SUCCESS"
    )


def set_organization_vat(client: TestClient, admin_token: str) -> None:
    response = client.put(
        "/api/v1/organization",
        json={"vat_number": "ATU99999999"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text


def run_for(client: TestClient, **partner: str) -> dict:
    created = client.post("/api/v1/partners", json=partner)
    assert created.status_code == 201, created.text
    started = client.post(f"/api/v1/partners/{created.json()['id']}/runs")
    assert started.status_code == 202, started.text
    response = client.get(f"/api/v1/runs/{started.json()['id']}")
    assert response.status_code == 200, response.text
    return response.json()


def levels(run: dict) -> dict[str, str]:
    return {reason["source"]: reason["level"] for reason in run["overall"]["reasons"]}


def test_every_source_ok_is_green(
    client: TestClient, db: Session, admin_token: str
) -> None:
    import_bmf_list(db)
    set_organization_vat(client, admin_token)

    run = run_for(client, vat_number=NOT_ON_BMF_LIST)

    assert run["overall"]["level"] == "GREEN"
    assert run["overall"]["summary"].startswith("No problems were found by VIES")
    assert levels(run) == {"VIES": "GREEN", "BMF": "GREEN", "HFU": "GREEN"}
    assert run["overall"]["disclaimer"] == DISCLAIMER


def test_partner_on_the_bmf_list_is_red(
    client: TestClient, db: Session, admin_token: str
) -> None:
    import_bmf_list(db)
    set_organization_vat(client, admin_token)

    run = run_for(client, vat_number=ON_BMF_LIST)

    assert run["overall"]["level"] == "RED"
    assert "A problem was found by the BMF list." in run["overall"]["summary"]
    assert levels(run)["BMF"] == "RED"


def test_a_failed_source_is_yellow_and_named(
    client: TestClient, db: Session, fake_vies
) -> None:
    import_bmf_list(db)
    fake_vies.answer = {"error": "MS_UNAVAILABLE"}

    run = run_for(client, vat_number=NOT_ON_BMF_LIST)

    # VIES failed, and HFU too (the organisation's own VAT number is not set).
    assert run["status"] == "incomplete"
    assert run["overall"]["level"] == "YELLOW"
    assert run["overall"]["summary"].startswith(
        "VIES and the HFU list could not be checked"
    )
    reasons = {r["source"]: r for r in run["overall"]["reasons"]}
    assert reasons["VIES"]["status"] == "ERROR"
    assert reasons["VIES"]["level"] == "YELLOW"


def test_partner_without_vat_number_is_green_on_what_applies(
    client: TestClient, db: Session
) -> None:
    import_bmf_list(db)

    run = run_for(client, company_register_number="987654z")

    assert run["overall"]["level"] == "GREEN"
    assert "VIES and the HFU list do not apply" in run["overall"]["summary"]
    # The tests run without Firmenbuch and GISA API keys: say they were not checked.
    assert run["overall"]["not_checked"] == ["FIRMENBUCH", "GISA"]
    assert run["overall"]["summary"].endswith(
        "The Firmenbuch and GISA are not set up on this server, so they were not checked."
    )


def test_partner_with_vat_number_only_has_nothing_left_out(
    client: TestClient, db: Session, admin_token: str
) -> None:
    import_bmf_list(db)
    set_organization_vat(client, admin_token)

    run = run_for(client, vat_number=NOT_ON_BMF_LIST)

    assert run["overall"]["not_checked"] == []
    assert "not set up" not in run["overall"]["summary"]


def test_partner_list_shows_the_latest_overall_result(
    client: TestClient, db: Session, admin_token: str
) -> None:
    import_bmf_list(db)
    set_organization_vat(client, admin_token)
    never_checked = client.post("/api/v1/partners", json={"vat_number": "ATU33333333"})
    assert never_checked.status_code == 201
    red = run_for(client, vat_number=ON_BMF_LIST)

    items = {p["vat_number"]: p for p in client.get("/api/v1/partners").json()["items"]}
    detail = client.get(f"/api/v1/partners/{red['partner_id']}").json()

    assert items["ATU33333333"]["latest_overall"] is None
    latest = items[ON_BMF_LIST]["latest_overall"]
    assert latest["run_id"] == red["id"]
    assert latest["level"] == "RED"
    assert latest["summary"] == red["overall"]["summary"]
    assert detail["latest_overall"]["run_id"] == red["id"]


def test_partner_list_uses_the_newest_finished_run(
    client: TestClient, db: Session, admin_token: str, fake_vies
) -> None:
    import_bmf_list(db)
    set_organization_vat(client, admin_token)
    first = run_for(client, vat_number=NOT_ON_BMF_LIST)
    fake_vies.answer = {"error": "MS_UNAVAILABLE"}

    second = client.post(f"/api/v1/partners/{first['partner_id']}/runs").json()

    latest = client.get(f"/api/v1/partners/{first['partner_id']}").json()[
        "latest_overall"
    ]
    assert first["overall"]["level"] == "GREEN"
    assert latest["run_id"] == second["id"]
    assert latest["level"] == "YELLOW"


def test_no_overall_result_while_the_run_is_running(client: TestClient) -> None:
    created = client.post("/api/v1/partners", json={"vat_number": NOT_ON_BMF_LIST})

    started = client.post(f"/api/v1/partners/{created.json()['id']}/runs").json()

    # The start answers before any source has answered.
    assert started["status"] == "running"
    assert started["overall"] is None
