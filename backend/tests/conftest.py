from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.adapters.vies import CheckStatus, ViesResult, get_vies_adapter
from app.db.models import CheckResult, Partner
from app.db.session import engine, get_db
from app.main import app

VALID_ANSWER = {
    "isValid": True,
    "requestDate": "2026-10-31T13:46:27.800Z",
    "userError": "VALID",
    "name": "Muster Bau GmbH",
    "address": "Hauptstrasse 1\nAT-1010 Wien",
    "vatNumber": "U12345678",
}


class FakeVies:
    """Stands in for VIES in API tests: no internet, answer chosen by the test."""

    def __init__(self) -> None:
        self.result = ViesResult(CheckStatus.VALID, VALID_ANSWER)
        self.checked: list[str] = []

    def check(self, vat_number: str) -> ViesResult:
        self.checked.append(vat_number)
        return self.result


@pytest.fixture(scope="session")
def database_ready() -> None:
    """Stop with a clear hint instead of long errors when the database is not ready."""
    try:
        tables = inspect(engine).get_table_names()
    except OperationalError:
        pytest.exit(
            "The database is not reachable. Start it with "
            "`docker compose -f infra/docker-compose.yml up -d`.",
            returncode=1,
        )
    if not {"partners", "check_results"} <= set(tables):
        pytest.exit(
            "The database tables are missing. Run `uv run alembic upgrade head` in `backend`.",
            returncode=1,
        )


@pytest.fixture
def db(database_ready: None) -> Iterator[Session]:
    """A session inside a transaction that is rolled back after the test.

    Tests use the real database (tables from `alembic upgrade head`),
    but leave no data behind. Each test starts without partners and checks;
    your own data comes back when the transaction is rolled back.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    session.execute(delete(CheckResult))
    session.execute(delete(Partner))
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def fake_vies() -> FakeVies:
    return FakeVies()


@pytest.fixture
def client(db: Session, fake_vies: FakeVies) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db
    # Tests never call the real VIES.
    app.dependency_overrides[get_vies_adapter] = lambda: fake_vies
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
