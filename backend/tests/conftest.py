from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.models import Partner
from app.db.session import engine, get_db
from app.main import app


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
    if "partners" not in tables:
        pytest.exit(
            "The database tables are missing. Run `uv run alembic upgrade head` in `backend`.",
            returncode=1,
        )


@pytest.fixture
def db(database_ready: None) -> Iterator[Session]:
    """A session inside a transaction that is rolled back after the test.

    Tests use the real database (tables from `alembic upgrade head`),
    but leave no data behind. Each test starts without partners; your own
    partners come back when the transaction is rolled back.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    session.execute(delete(Partner))
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
