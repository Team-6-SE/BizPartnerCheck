"""Partner directory (S3.2): edit, archive/restore, history, search details, isolation."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import CheckResult, Organization, Partner
from app.tenancy import TEST_ORGANIZATION_ID


def add_partner(client: TestClient, **fields: str) -> dict:
    response = client.post(
        "/api/v1/partners", json=fields or {"vat_number": "ATU12345678"}
    )
    assert response.status_code == 201
    return response.json()


def active_ids(client: TestClient) -> set[str]:
    return {item["id"] for item in client.get("/api/v1/partners").json()["items"]}


def archived_ids(client: TestClient) -> set[str]:
    return {item["id"] for item in client.get("/api/v1/partners/archived").json()}


# --- Edit (T3.2.2) -----------------------------------------------------------


def test_edit_changes_the_name_and_keeps_all_checks(
    client: TestClient, db: Session
) -> None:
    partner = add_partner(client, vat_number="ATU12345678", company_name="Old GmbH")
    first = client.post(f"/api/v1/partners/{partner['id']}/checks/vies").json()
    stored_before = db.get(CheckResult, uuid.UUID(first["id"]))
    raw_before = dict(stored_before.raw_response)

    response = client.patch(
        f"/api/v1/partners/{partner['id']}", json={"company_name": "  New GmbH  "}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["company_name"] == "New GmbH"
    assert body["vat_number"] == "ATU12345678"
    history = client.get(f"/api/v1/partners/{partner['id']}/checks").json()
    assert [check["id"] for check in history] == [first["id"]]
    db.refresh(stored_before)
    assert stored_before.raw_response == raw_before


def test_edit_with_empty_name_removes_it(client: TestClient) -> None:
    partner = add_partner(client, vat_number="ATU12345678", company_name="Old GmbH")

    response = client.patch(
        f"/api/v1/partners/{partner['id']}", json={"company_name": " "}
    )

    assert response.status_code == 200
    assert response.json()["company_name"] is None


def test_edit_without_fields_changes_nothing(client: TestClient) -> None:
    partner = add_partner(client, vat_number="ATU12345678", company_name="Old GmbH")

    response = client.patch(f"/api/v1/partners/{partner['id']}", json={})

    assert response.status_code == 200
    assert response.json()["company_name"] == "Old GmbH"


# --- Adding a missing identifier (T3.3.3) -----------------------------------


def test_edit_adds_a_missing_register_number_and_keeps_all_checks(
    client: TestClient,
) -> None:
    partner = add_partner(client, vat_number="ATU12345678")
    first = client.post(f"/api/v1/partners/{partner['id']}/checks/vies").json()

    response = client.patch(
        f"/api/v1/partners/{partner['id']}",
        json={"company_register_number": "FN 123456 a"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["company_register_number"] == "123456a"
    assert body["vat_number"] == "ATU12345678"
    history = client.get(f"/api/v1/partners/{partner['id']}/checks").json()
    assert [check["id"] for check in history] == [first["id"]]


def test_edit_adds_a_missing_vat_number(client: TestClient) -> None:
    partner = add_partner(client, company_register_number="123456a")

    response = client.patch(
        f"/api/v1/partners/{partner['id']}", json={"vat_number": "atu 1234 5678"}
    )

    assert response.status_code == 200
    assert response.json()["vat_number"] == "ATU12345678"


def test_edit_never_changes_a_number_that_is_set(client: TestClient) -> None:
    partner = add_partner(client, vat_number="ATU12345678")

    response = client.patch(
        f"/api/v1/partners/{partner['id']}", json={"vat_number": "ATU87654321"}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "identifier_locked"
    assert response.json()["detail"]["field"] == "vat_number"
    stored = client.get(f"/api/v1/partners/{partner['id']}").json()
    assert stored["vat_number"] == "ATU12345678"


def test_edit_never_removes_a_number_that_is_set(client: TestClient) -> None:
    partner = add_partner(
        client, vat_number="ATU12345678", company_register_number="123456a"
    )

    response = client.patch(
        f"/api/v1/partners/{partner['id']}", json={"company_register_number": ""}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "identifier_locked"


def test_edit_with_the_same_number_in_another_spelling_changes_nothing(
    client: TestClient,
) -> None:
    partner = add_partner(
        client, vat_number="ATU12345678", company_register_number="123456a"
    )

    response = client.patch(
        f"/api/v1/partners/{partner['id']}",
        json={
            "vat_number": "atu12345678",
            "company_register_number": "FN 123456 a",
            "company_name": "Same GmbH",
        },
    )

    assert response.status_code == 200
    assert response.json()["company_name"] == "Same GmbH"


def test_edit_with_an_empty_missing_number_changes_nothing(client: TestClient) -> None:
    partner = add_partner(client, vat_number="ATU12345678")

    response = client.patch(
        f"/api/v1/partners/{partner['id']}", json={"company_register_number": "  "}
    )

    assert response.status_code == 200
    assert response.json()["company_register_number"] is None


def test_edit_refuses_an_invalid_number_and_changes_nothing(client: TestClient) -> None:
    partner = add_partner(client, vat_number="ATU12345678")

    response = client.patch(
        f"/api/v1/partners/{partner['id']}",
        json={"company_register_number": "not a number", "company_name": "X GmbH"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_register_number_format"
    stored = client.get(f"/api/v1/partners/{partner['id']}").json()
    assert stored["company_register_number"] is None
    assert stored["company_name"] is None


def test_edit_refuses_a_number_another_partner_has(client: TestClient) -> None:
    add_partner(client, vat_number="ATU11111111", company_register_number="123456a")
    partner = add_partner(client, vat_number="ATU12345678")

    response = client.patch(
        f"/api/v1/partners/{partner['id']}",
        json={"company_register_number": "123456a"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "duplicate_partner"
    assert response.json()["detail"]["field"] == "company_register_number"


# --- Archive and restore (T3.2.3) -------------------------------------------


def test_archived_partner_is_hidden_and_can_be_restored(client: TestClient) -> None:
    partner = add_partner(client)
    client.post(f"/api/v1/partners/{partner['id']}/checks/vies")

    archived = client.patch(f"/api/v1/partners/{partner['id']}/archive")

    assert archived.status_code == 200
    assert archived.json()["is_archived"] is True
    assert partner["id"] not in active_ids(client)
    assert partner["id"] in archived_ids(client)
    # The history stays.
    assert len(client.get(f"/api/v1/partners/{partner['id']}/checks").json()) == 1

    restored = client.patch(f"/api/v1/partners/{partner['id']}/restore")

    assert restored.status_code == 200
    assert restored.json()["is_archived"] is False
    assert partner["id"] in active_ids(client)
    assert partner["id"] not in archived_ids(client)


def test_archived_partners_are_not_counted_in_the_active_list(
    client: TestClient,
) -> None:
    keep = add_partner(client, vat_number="ATU12345678")
    gone = add_partner(client, vat_number="DE123456789")
    client.patch(f"/api/v1/partners/{gone['id']}/archive")

    body = client.get("/api/v1/partners").json()

    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [keep["id"]]


@pytest.mark.parametrize("source", ["vies", "bmf"])
def test_archived_partner_cannot_be_checked(client: TestClient, source: str) -> None:
    partner = add_partner(client)
    client.patch(f"/api/v1/partners/{partner['id']}/archive")

    response = client.post(f"/api/v1/partners/{partner['id']}/checks/{source}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "partner_archived"
    assert client.get(f"/api/v1/partners/{partner['id']}/checks").json() == []


@pytest.mark.parametrize("action", ["archive", "restore"])
def test_archive_and_restore_unknown_partner_is_404(
    client: TestClient, action: str
) -> None:
    response = client.patch(f"/api/v1/partners/{uuid.uuid4()}/{action}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "partner_not_found"


# --- History (T3.2.4) --------------------------------------------------------


def test_history_is_newest_first(client: TestClient, db: Session) -> None:
    partner = add_partner(client)
    now = datetime.now(UTC)
    for days_ago in (3, 1, 2):
        db.add(
            CheckResult(
                partner_id=uuid.UUID(partner["id"]),
                source="vies",
                status="OK",
                checked_at=now - timedelta(days=days_ago),
                raw_response={"isValid": True, "userError": "VALID"},
            )
        )
    db.flush()

    history = client.get(f"/api/v1/partners/{partner['id']}/checks").json()

    times = [check["checked_at"] for check in history]
    assert len(times) == 3
    assert times == sorted(times, reverse=True)


def test_history_of_unknown_partner_is_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/partners/{uuid.uuid4()}/checks")

    assert response.status_code == 404


# --- Search and sorting details ------------------------------------------------


def test_search_finds_register_number_written_with_fn(client: TestClient) -> None:
    add_partner(client, company_register_number="123456a")
    add_partner(client, company_register_number="654321b")

    body = client.get("/api/v1/partners", params={"search": "FN 123456a"}).json()

    assert [item["company_register_number"] for item in body["items"]] == ["123456a"]


def test_search_finds_vat_number_written_with_spaces(client: TestClient) -> None:
    add_partner(client, vat_number="ATU12345678")
    add_partner(client, vat_number="DE123456789")

    body = client.get("/api/v1/partners", params={"search": "atu 1234"}).json()

    assert [item["vat_number"] for item in body["items"]] == ["ATU12345678"]


@pytest.mark.parametrize("term", ["%", "_", "100%"])
def test_search_wildcards_are_taken_literally(client: TestClient, term: str) -> None:
    add_partner(client, vat_number="ATU12345678", company_name="Muster GmbH")

    body = client.get("/api/v1/partners", params={"search": term}).json()

    assert body["total"] == 0


def test_search_finds_names_with_percent(client: TestClient) -> None:
    add_partner(client, vat_number="ATU12345678", company_name="100% Bio GmbH")
    add_partner(client, vat_number="DE123456789", company_name="1000 Teile GmbH")

    body = client.get("/api/v1/partners", params={"search": "100%"}).json()

    assert [item["company_name"] for item in body["items"]] == ["100% Bio GmbH"]


def test_invalid_sort_field_uses_the_error_format(client: TestClient) -> None:
    response = client.get("/api/v1/partners", params={"sort_by": "password"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_sort"
    assert detail["field"] == "sort_by"


@pytest.mark.parametrize("order", ["asc", "desc"])
def test_partners_without_a_name_come_last(client: TestClient, order: str) -> None:
    add_partner(client, vat_number="ATU12345678")
    add_partner(client, vat_number="DE123456789", company_name="Alpha GmbH")
    add_partner(client, vat_number="FR12345678901", company_name="Beta GmbH")

    body = client.get(
        "/api/v1/partners", params={"sort_by": "company_name", "sort_order": order}
    ).json()

    names = [item["company_name"] for item in body["items"]]
    assert names[-1] is None
    assert names[:2] == (
        ["Alpha GmbH", "Beta GmbH"] if order == "asc" else ["Beta GmbH", "Alpha GmbH"]
    )


# --- Isolation (S2.3: every endpoint that reads or changes business data) ------


@pytest.fixture
def other_organization_headers(db: Session, tokens) -> dict[str, str]:
    other = Organization(name="Other customer")
    db.add(other)
    db.flush()
    token = tokens.make(extra={"organization_id": str(other.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "", None),
        ("GET", "/checks", None),
        ("PATCH", "", {"company_name": "Taken over"}),
        ("PATCH", "/archive", None),
        ("PATCH", "/restore", None),
        ("POST", "/checks/vies", None),
        ("POST", "/checks/bmf", None),
    ],
)
def test_other_organization_gets_404_and_changes_nothing(
    client: TestClient,
    db: Session,
    other_organization_headers: dict[str, str],
    method: str,
    path: str,
    body: dict | None,
) -> None:
    partner = add_partner(client, vat_number="ATU12345678", company_name="Mine GmbH")

    response = client.request(
        method,
        f"/api/v1/partners/{partner['id']}{path}",
        json=body,
        headers=other_organization_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "partner_not_found"
    saved = db.get(Partner, uuid.UUID(partner["id"]))
    db.refresh(saved)
    assert saved.organization_id == TEST_ORGANIZATION_ID
    assert saved.company_name == "Mine GmbH"
    assert saved.is_archived is False
    assert client.get(f"/api/v1/partners/{partner['id']}/checks").json() == []


def test_other_organization_does_not_see_archived_partners(
    client: TestClient, other_organization_headers: dict[str, str]
) -> None:
    partner = add_partner(client)
    client.patch(f"/api/v1/partners/{partner['id']}/archive")

    response = client.get(
        "/api/v1/partners/archived", headers=other_organization_headers
    )

    assert response.status_code == 200
    assert response.json() == []
